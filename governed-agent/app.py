"""Agente mínimo: UI, API OpenAI-compatible y única salida LLM vía Plano."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

PLANO_BASE_URL = os.getenv("PLANO_BASE_URL", "http://plano:12000")
MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "12000"))
STATIC_DIR = Path(__file__).parent / "static"

MODEL_MAP = {
    "chatgpt": "custom/local-chatgpt",
    "claude": "custom/local-claude",
    "grok": "custom/local-grok",
}

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I | re.S),
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b", re.I),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
]

app = FastAPI(title="Governed AI Desktop Agent", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def redact_text(value: str) -> tuple[str, int]:
    redactions = 0
    for pattern in SECRET_PATTERNS:
        value, count = pattern.subn("[REDACTED_BY_AGENT]", value)
        redactions += count
    return value, redactions


def sanitize_messages(messages: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages debe ser una lista no vacía")
    if len(messages) > 64:
        raise ValueError("La conversación supera el máximo de 64 mensajes")

    result: list[dict[str, Any]] = []
    total_redactions = 0
    total_chars = 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Cada mensaje debe tener un rol permitido")
        item = dict(message)
        content = item.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
            item["content"], count = redact_text(content)
            total_redactions += count
        elif isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                new_part = dict(part)
                if isinstance(new_part.get("text"), str):
                    total_chars += len(new_part["text"])
                    new_part["text"], count = redact_text(new_part["text"])
                    total_redactions += count
                parts.append(new_part)
            item["content"] = parts
        result.append(item)

    if total_chars > MAX_PROMPT_CHARS:
        raise ValueError(f"El prompt supera el máximo de {MAX_PROMPT_CHARS} caracteres")
    return result, total_redactions


def sanitize_output(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)[0]
    if isinstance(value, list):
        return [sanitize_output(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_output(item) for key, item in value.items()}
    return value


def choose_model(provider: str, requested: str | None = None) -> str:
    if requested and requested.startswith(("custom/", "openai/", "anthropic/", "xai/", "chatgpt/")):
        return requested
    return MODEL_MAP.get(provider.casefold(), MODEL_MAP["chatgpt"])


async def forward_json(path: str, payload: dict[str, Any]) -> JSONResponse:
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(f"{PLANO_BASE_URL}{path}", json=payload)
    try:
        content = sanitize_output(response.json())
    except ValueError:
        content = {"error": {"message": response.text[:2000]}}
    headers = {
        "x-agent-egress": "plano-only",
        "x-plano-upstream-status": str(response.status_code),
    }
    return JSONResponse(status_code=response.status_code, content=content, headers=headers)


async def build_stream_response(path: str, payload: dict[str, Any], redactions: int = 0):
    """Abre el upstream antes de enviar headers al cliente para preservar errores 4xx."""
    client = httpx.AsyncClient(timeout=None)
    request = client.build_request("POST", f"{PLANO_BASE_URL}{path}", json=payload)
    response = await client.send(request, stream=True)

    if response.status_code >= 400:
        raw = await response.aread()
        await response.aclose()
        await client.aclose()
        try:
            content = sanitize_output(json.loads(raw.decode("utf-8", errors="replace")))
        except ValueError:
            content = {"error": {"message": raw.decode("utf-8", errors="replace")[:2000]}}
        return JSONResponse(
            status_code=response.status_code,
            content=content,
            headers={
                "x-agent-egress": "plano-only",
                "x-agent-redactions": str(redactions),
                "x-plano-upstream-status": str(response.status_code),
            },
        )

    async def iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                sanitized = sanitize_output(chunk.decode("utf-8", errors="replace"))
                yield sanitized.encode("utf-8")
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        iterator(),
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "text/event-stream").split(";", 1)[0],
        headers={"x-agent-egress": "plano-only", "x-agent-redactions": str(redactions)},
    )


@app.get("/")
async def ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "governed-agent", "egress": PLANO_BASE_URL}


@app.post("/api/policy-check")
async def policy_check(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "") if isinstance(body, dict) else ""
    provider = body.get("provider", "chatgpt") if isinstance(body, dict) else "chatgpt"
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse(status_code=400, content={"allowed": False, "message": "El prompt está vacío."})
    if len(prompt) > MAX_PROMPT_CHARS:
        return JSONResponse(status_code=413, content={"allowed": False, "message": "El prompt excede el límite permitido."})

    payload = {
        "model": choose_model(str(provider)),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "metadata": {"provider": str(provider), "source": "browser-extension-preflight"},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{PLANO_BASE_URL}/v1/chat/completions", json=payload)
    if response.status_code >= 400:
        try:
            error = response.json()
            message = error.get("error", {}).get("message") or error.get("detail", {}).get("message") or str(error)
        except ValueError:
            message = response.text[:1000]
        return JSONResponse(
            status_code=200,
            content={"allowed": False, "message": message, "plano_status": response.status_code},
        )
    return {"allowed": True, "message": "Solicitud permitida por Plano.", "plano_status": response.status_code}


@app.post("/api/chat")
async def api_chat(request: Request):
    body = await request.json()
    provider = str(body.get("provider", "chatgpt"))
    try:
        messages, redactions = sanitize_messages(body.get("messages", []))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": {"message": str(exc)}})

    payload = {
        "model": choose_model(provider, body.get("model")),
        "messages": messages,
        "stream": bool(body.get("stream", False)),
        "metadata": {"provider": provider, "source": "governed-desktop", "agent_redactions": redactions},
    }
    if payload["stream"]:
        return await build_stream_response("/v1/chat/completions", payload, redactions)
    response = await forward_json("/v1/chat/completions", payload)
    response.headers["x-agent-redactions"] = str(redactions)
    return response


@app.post("/v1/chat/completions")
async def openai_compatible(request: Request):
    body = await request.json()
    try:
        messages, redactions = sanitize_messages(body.get("messages", []))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": {"message": str(exc)}})
    payload = dict(body)
    payload["messages"] = messages
    payload["model"] = choose_model(str(body.get("provider", "chatgpt")), body.get("model"))
    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata.update({"source": "governed-agent-openai-api", "agent_redactions": redactions})
    if payload.get("stream"):
        return await build_stream_response("/v1/chat/completions", payload, redactions)
    return await forward_json("/v1/chat/completions", payload)
