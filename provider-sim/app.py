"""Proveedor LLM local y determinista para pruebas end-to-end sin credenciales."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter, deque
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

app = FastAPI(title="Local Provider Simulator", version="1.0.0")
CALLS: Counter[str] = Counter()
RECENT: deque[dict[str, Any]] = deque(maxlen=100)
AUDIT_URL = os.getenv("AUDIT_URL", "http://audit-dashboard:10700/ingest")
AUDIT_TOKEN = os.getenv("AUDIT_INGEST_TOKEN", "plano-audit-ingest-demo")


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
    if "gemini" in lowered:
        return "Gemini (simulado)"
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


async def complete_audit(body: dict[str, Any], text: str, status_code: int = 200) -> None:
    metadata = body.get("metadata", {}) if isinstance(body.get("metadata"), dict) else {}
    audit_id = metadata.get("audit_id")
    if not audit_id or metadata.get("audit_phase") == "preflight":
        return
    payload = {
        "audit_id": str(audit_id),
        "response_text": text,
        "response_bytes": len(text.encode("utf-8")),
        "status_code": status_code,
        "decision": "allow",
        "filtered": False,
        "rule": "allowed",
        "state": "completed",
        "properties": {"completion_source": "provider-sim"},
    }
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            await client.post(AUDIT_URL, json=payload, headers={"x-audit-token": AUDIT_TOKEN})
    except Exception:
        return


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
    await complete_audit(body, text)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    record("/v1/chat/completions", body)
    if body.get("stream"):
        return StreamingResponse(openai_stream(body), media_type="text/event-stream")
    content = response_text(body)
    model = str(body.get("model", "custom/local-chatgpt"))
    await complete_audit(body, content)
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
    await complete_audit(body, content)
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
    content = response_text(body)
    await complete_audit(body, content)
    return {
        "id": f"msg_{uuid.uuid4().hex[:20]}",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "custom/local-claude"),
        "content": [{"type": "text", "text": content}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 20},
    }


@app.get("/web-fixture/{provider}", response_class=HTMLResponse)
async def web_fixture(provider: str):
    safe_provider = provider if provider in {"chatgpt", "claude", "grok", "gemini"} else "gemini"
    return f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><title>{safe_provider.title()} Free Web Fixture</title>
<style>body{{font:16px system-ui;max-width:760px;margin:40px auto;background:#f7f9fc;color:#172033}}form{{display:flex;gap:10px}}textarea{{flex:1;min-height:90px;padding:12px}}button{{padding:0 22px}}[data-message-author-role]{{padding:13px;margin:12px 0;border-radius:10px;background:#e9eef7}}[data-message-author-role=assistant]{{background:#def7e9}}</style></head>
<body><h1>{safe_provider.title()} · fixture de cuenta free</h1><p>Esta página controlada valida la extensión: Plano autoriza o bloquea antes del submit y la respuesta queda auditada.</p>
<div id='messages'></div><form id='composer'><textarea aria-label='Prompt' placeholder='Escribe un prompt'></textarea><button type='submit' aria-label='Enviar'>Enviar</button></form>
<script>const form=document.querySelector('#composer'),box=form.querySelector('textarea');form.addEventListener('submit',event=>{{event.preventDefault();const prompt=box.value.trim();if(!prompt)return;box.value='';const messages=document.querySelector('#messages');const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent=prompt;messages.append(user);setTimeout(()=>{{const answer=document.createElement('div');answer.dataset.messageAuthorRole='assistant';answer.textContent='{safe_provider.title()} fixture: respuesta generada después de la autorización de Plano para: '+prompt;messages.append(answer)}},700)}});const fixtureParams=new URLSearchParams(location.search);if(fixtureParams.get('autotest')==='1'){{box.value=fixtureParams.get('prompt')||'Explica la fotosíntesis desde {safe_provider.title()} free';setTimeout(()=>form.requestSubmit(),1200)}}</script></body></html>"""


@app.get("/")
async def index():
    return {
        "service": "provider-sim",
        "purpose": "Upstream OpenAI/Anthropic-compatible para pruebas sin credenciales",
        "health": "/health",
        "calls": "/calls",
        "reset": "POST /reset",
        "configuration": "Este servicio es determinista; los proveedores reales se habilitan con docker-compose.real-api.yml",
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
