"""Proveedor LLM local y determinista para pruebas end-to-end sin credenciales."""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter, deque
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Local Provider Simulator", version="1.0.0")
CALLS: Counter[str] = Counter()
RECENT: deque[dict[str, Any]] = deque(maxlen=100)


def last_user_text(body: dict[str, Any]) -> str:
    messages = body.get("messages", [])
    if isinstance(messages, list):
        for item in reversed(messages):
            if isinstance(item, dict) and item.get("role") == "user":
                content = item.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        str(part.get("text", part.get("input_text", "")))
                        for part in content
                        if isinstance(part, dict)
                    )
    value = body.get("input", body.get("prompt", ""))
    if isinstance(value, str):
        return value
    return ""


def provider_label(model: str) -> str:
    lowered = model.casefold()
    if "claude" in lowered:
        return "Claude (simulado)"
    if "grok" in lowered:
        return "Grok (simulado)"
    if "chatgpt" in lowered or "gpt" in lowered:
        return "ChatGPT (simulado)"
    if "policy" in lowered:
        return "Plano Policy Backend"
    return "Proveedor local"


def response_text(body: dict[str, Any]) -> str:
    model = str(body.get("model", "custom/local-chatgpt"))
    prompt = last_user_text(body)
    return f"{provider_label(model)}: solicitud permitida por Plano. Eco: {prompt[:240]}"


def record(path: str, body: dict[str, Any]) -> None:
    model = str(body.get("model", "unknown"))
    CALLS["total"] += 1
    CALLS[f"path:{path}"] += 1
    CALLS[f"model:{model}"] += 1
    RECENT.appendleft(
        {
            "timestamp": int(time.time()),
            "path": path,
            "model": model,
            "stream": bool(body.get("stream", False)),
            "policy_decision": body.get("metadata", {}).get("plano_policy_decision")
            if isinstance(body.get("metadata"), dict)
            else None,
        }
    )


async def openai_stream(body: dict[str, Any]) -> AsyncIterator[str]:
    response_id = f"chatcmpl-{uuid.uuid4().hex[:20]}"
    model = str(body.get("model", "custom/local-chatgpt"))
    text = response_text(body)
    chunks = [text[index : index + 24] for index in range(0, len(text), 24)] or [""]
    for index, chunk in enumerate(chunks):
        payload = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": ({"role": "assistant", "content": chunk} if index == 0 else {"content": chunk}),
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    done = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    record("/v1/chat/completions", body)
    if body.get("stream"):
        return StreamingResponse(openai_stream(body), media_type="text/event-stream")
    content = response_text(body)
    model = str(body.get("model", "custom/local-chatgpt"))
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:20]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 20, "total_tokens": 32},
    }


@app.post("/v1/responses")
async def responses(request: Request):
    body = await request.json()
    record("/v1/responses", body)
    content = response_text(body)
    return {
        "id": f"resp_{uuid.uuid4().hex[:20]}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": body.get("model", "custom/local-chatgpt"),
        "output": [
            {
                "id": f"msg_{uuid.uuid4().hex[:16]}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": content, "annotations": []}],
            }
        ],
    }


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    body = await request.json()
    record("/v1/messages", body)
    return {
        "id": f"msg_{uuid.uuid4().hex[:20]}",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "custom/local-claude"),
        "content": [{"type": "text", "text": response_text(body)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 20},
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "provider-sim"}


@app.get("/calls")
async def calls():
    return JSONResponse({"counters": dict(CALLS), "recent": list(RECENT)})


@app.post("/reset")
async def reset():
    CALLS.clear()
    RECENT.clear()
    return {"status": "reset"}
