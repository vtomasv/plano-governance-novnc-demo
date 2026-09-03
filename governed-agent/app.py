"""Agente gobernado: única salida LLM vía Plano y auditoría correlacionada."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

PLANO_BASE_URL = os.getenv("PLANO_BASE_URL", "http://plano:12000")
AUDIT_URL = os.getenv("AUDIT_URL", "http://audit-dashboard:10700/ingest")
AUDIT_TOKEN = os.getenv("AUDIT_INGEST_TOKEN", "plano-audit-ingest-demo")
MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "12000"))
STATIC_DIR = Path(__file__).parent / "static"

MODEL_MAP = {
    "chatgpt": "custom/local-chatgpt",
    "claude": "custom/local-claude",
    "grok": "custom/local-grok",
    "gemini": "custom/local-gemini",
}

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I | re.S),
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b", re.I),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
]

app = FastAPI(title="Governed AI Desktop Agent", version="1.2.0")
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
    if requested and requested.startswith(("custom/", "openai/", "anthropic/", "xai/", "google/", "chatgpt/")):
        return requested
    return MODEL_MAP.get(provider.casefold(), MODEL_MAP["chatgpt"])


def prompt_text(messages: list[dict[str, Any]]) -> str:
    texts: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("text"))
    return "\n".join(texts)


def response_text(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    try:
        return str(value["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        pass
    try:
        return str(value["output"][0]["content"][0]["text"])
    except (KeyError, IndexError, TypeError):
        pass
    if isinstance(value.get("content"), list):
        return "\n".join(str(item.get("text", "")) for item in value["content"] if isinstance(item, dict))
    error = value.get("error") or value.get("detail")
    if isinstance(error, dict) and isinstance(error.get("error"), dict):
        error = error["error"]
    if isinstance(error, dict):
        return str(error.get("message") or json.dumps(error, ensure_ascii=False))
    return ""


def response_payloads(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    payloads = [value]
    nested = value.get("agent_response")
    if isinstance(nested, str):
        try:
            nested = json.loads(nested)
        except ValueError:
            nested = None
    if isinstance(nested, dict):
        payloads.insert(0, nested)
    return payloads


def error_detail(value: Any) -> tuple[str, str | None, str | None]:
    fallback = ""
    for payload in response_payloads(value):
        detail = payload.get("error", payload.get("detail", payload.get("message", {})))
        if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
            detail = detail["error"]
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("detail") or detail.get("type") or "")
            if message:
                return message, detail.get("code"), detail.get("decision_id")
        elif detail:
            text = str(detail)
            if text != "FilterChainError":
                return text, None, None
            fallback = text
    return fallback or "Solicitud rechazada por Plano.", None, None


def policy_identifiers(value: Any) -> tuple[str | None, str | None]:
    audit_id = decision_id = None
    for payload in response_payloads(value):
        audit_id = payload.get("audit_id") or audit_id
        decision_id = payload.get("decision_id") or decision_id
        detail = payload.get("error")
        if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
            detail = detail["error"]
        if isinstance(detail, dict):
            audit_id = detail.get("audit_id") or audit_id
            decision_id = detail.get("decision_id") or decision_id
    return audit_id, decision_id


async def audit_event(payload: dict[str, Any]) -> None:
    """Auditoría best-effort: nunca altera la decisión ni el flujo LLM."""
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            await client.post(AUDIT_URL, json=payload, headers={"x-audit-token": AUDIT_TOKEN})
    except Exception:
        return


def audit_base(*, audit_id: str, provider: str, source: str, model: str, prompt: str, redactions: int, streaming: bool, started: float, client: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
    return {
        "audit_id": audit_id,
        "conversation_id": conversation_id,
        "source": source,
        "client": client or source,
        "provider": provider,
        "model": model,
        "endpoint": "/v1/chat/completions",
        "prompt_text": prompt,
        "redaction_count": redactions,
        "streaming": streaming,
        "request_bytes": len(prompt.encode("utf-8")),
        "state": "evaluating",
        "properties": {"egress": "plano-only"},
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
    }


async def forward_json(path: str, payload: dict[str, Any], audit: dict[str, Any], started: float) -> JSONResponse:
    await audit_event(audit)
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            upstream = await client.post(f"{PLANO_BASE_URL}{path}", json=payload)
        try:
            content = sanitize_output(upstream.json())
        except ValueError:
            content = {"error": {"message": upstream.text[:2000]}}
        message, rule, decision_id = error_detail(content) if upstream.status_code >= 400 else ("", None, None)
        text = response_text(content)
        await audit_event({
            "audit_id": audit["audit_id"],
            "response_text": text,
            "response_bytes": len(upstream.content),
            "status_code": upstream.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "decision": "deny" if upstream.status_code >= 400 else "allow",
            "filtered": upstream.status_code >= 400,
            "rule": rule or ("allowed" if upstream.status_code < 400 else "upstream_error"),
            "decision_id": decision_id,
            "policy_message": message if upstream.status_code >= 400 else "Solicitud permitida por Plano.",
            "state": "blocked" if upstream.status_code == 403 else ("completed" if upstream.status_code < 400 else "error"),
        })
        return JSONResponse(
            status_code=upstream.status_code,
            content=content,
            headers={"x-agent-egress": "plano-only", "x-plano-upstream-status": str(upstream.status_code), "x-audit-id": audit["audit_id"]},
        )
    except Exception as exc:
        await audit_event({"audit_id": audit["audit_id"], "state": "error", "error_type": type(exc).__name__, "error_message": str(exc), "duration_ms": round((time.monotonic() - started) * 1000, 1)})
        return JSONResponse(status_code=502, content={"error": {"message": "Plano no está disponible."}}, headers={"x-audit-id": audit["audit_id"]})


async def build_stream_response(path: str, payload: dict[str, Any], audit: dict[str, Any], started: float):
    """Abre upstream antes de headers y conserva una copia textual de los deltas."""
    await audit_event(audit)
    client = httpx.AsyncClient(timeout=None)
    request = client.build_request("POST", f"{PLANO_BASE_URL}{path}", json=payload)
    try:
        upstream = await client.send(request, stream=True)
    except Exception as exc:
        await client.aclose()
        await audit_event({"audit_id": audit["audit_id"], "state": "error", "error_type": type(exc).__name__, "error_message": str(exc)})
        return JSONResponse(status_code=502, content={"error": {"message": "Plano no está disponible."}}, headers={"x-audit-id": audit["audit_id"]})

    if upstream.status_code >= 400:
        raw = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        try:
            content = sanitize_output(json.loads(raw.decode("utf-8", errors="replace")))
        except ValueError:
            content = {"error": {"message": raw.decode("utf-8", errors="replace")[:2000]}}
        message, rule, decision_id = error_detail(content)
        await audit_event({
            "audit_id": audit["audit_id"], "response_text": message, "response_bytes": len(raw),
            "status_code": upstream.status_code, "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "decision": "deny", "filtered": True, "rule": rule, "decision_id": decision_id,
            "policy_message": message, "state": "blocked" if upstream.status_code == 403 else "error",
        })
        return JSONResponse(status_code=upstream.status_code, content=content, headers={"x-agent-egress": "plano-only", "x-audit-id": audit["audit_id"]})

    async def iterator() -> AsyncIterator[bytes]:
        fragments: list[str] = []
        response_bytes = 0
        buffer = ""
        try:
            async for chunk in upstream.aiter_bytes():
                response_bytes += len(chunk)
                sanitized = sanitize_output(chunk.decode("utf-8", errors="replace"))
                buffer += sanitized
                events = buffer.split("\n\n")
                buffer = events.pop() or ""
                for event in events:
                    for line in event.splitlines():
                        if not line.startswith("data: ") or line[6:] == "[DONE]":
                            continue
                        try:
                            data = json.loads(line[6:])
                            fragment = data.get("choices", [{}])[0].get("delta", {}).get("content")
                            if fragment:
                                fragments.append(str(fragment))
                        except (ValueError, KeyError, IndexError, TypeError):
                            pass
                yield sanitized.encode("utf-8")
        finally:
            await upstream.aclose()
            await client.aclose()
            await audit_event({
                "audit_id": audit["audit_id"], "response_text": "".join(fragments), "response_bytes": response_bytes,
                "status_code": upstream.status_code, "duration_ms": round((time.monotonic() - started) * 1000, 1),
                "decision": "allow", "filtered": False, "rule": "allowed", "state": "completed",
            })

    return StreamingResponse(
        iterator(), status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/event-stream").split(";", 1)[0],
        headers={"x-agent-egress": "plano-only", "x-agent-redactions": str(audit.get("redaction_count", 0)), "x-audit-id": audit["audit_id"]},
    )


@app.get("/")
async def ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "governed-agent", "egress": PLANO_BASE_URL, "audit": AUDIT_URL}


@app.post("/api/policy-check")
async def policy_check(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "") if isinstance(body, dict) else ""
    provider = str(body.get("provider", "chatgpt")) if isinstance(body, dict) else "chatgpt"
    audit_id = str(body.get("audit_id") or uuid.uuid4()) if isinstance(body, dict) else str(uuid.uuid4())
    conversation_id = str(body.get("conversation_id") or "") or None if isinstance(body, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse(status_code=400, content={"allowed": False, "message": "El prompt está vacío."})
    if len(prompt) > MAX_PROMPT_CHARS:
        return JSONResponse(status_code=413, content={"allowed": False, "message": "El prompt excede el límite permitido."})

    prompt, redactions = redact_text(prompt)
    started = time.monotonic()
    model = choose_model(provider)
    audit = audit_base(audit_id=audit_id, provider=provider, source="browser-free-web", model=model, prompt=prompt, redactions=redactions, streaming=True, started=time.time(), client=f"{provider}-free-web", conversation_id=conversation_id)
    audit["target_host"] = str(body.get("target_host") or "")[:255]
    audit["target_path"] = str(body.get("target_path") or "")[:512]
    await audit_event(audit)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "metadata": {"provider": provider, "source": "browser-extension-preflight", "client": f"{provider}-free-web", "audit_id": audit_id, "audit_phase": "preflight"},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{PLANO_BASE_URL}/v1/chat/completions", json=payload)
    except Exception as exc:
        await audit_event({"audit_id": audit_id, "state": "error", "error_type": type(exc).__name__, "error_message": str(exc), "duration_ms": round((time.monotonic() - started) * 1000, 1)})
        return {"allowed": False, "message": "Plano no está disponible; envío detenido en modo cerrado.", "audit_id": audit_id, "plano_status": 503}
    if response.status_code >= 400:
        try:
            error = response.json()
            message, rule, decision_id = error_detail(error)
            _nested_audit_id, nested_decision_id = policy_identifiers(error)
            decision_id = decision_id or nested_decision_id
        except ValueError:
            message, rule, decision_id = response.text[:1000], "invalid_response", None
        await audit_event({
            "audit_id": audit_id, "decision": "deny", "filtered": True, "rule": rule,
            "decision_id": decision_id, "policy_message": message, "response_text": message,
            "status_code": response.status_code, "duration_ms": round((time.monotonic() - started) * 1000, 1), "state": "blocked",
        })
        return {"allowed": False, "message": message, "audit_id": audit_id, "decision_id": decision_id, "plano_status": response.status_code}
    await audit_event({
        "audit_id": audit_id, "decision": "allow", "filtered": False, "rule": "allowed",
        "policy_message": "Solicitud permitida por Plano.", "status_code": response.status_code,
        "duration_ms": round((time.monotonic() - started) * 1000, 1), "state": "authorized",
    })
    return {"allowed": True, "message": "Solicitud permitida por Plano. Enviando al proveedor…", "audit_id": audit_id, "plano_status": response.status_code}


@app.post("/api/web-result")
async def web_result(request: Request):
    body = await request.json()
    audit_id = str(body.get("audit_id") or "")
    if not audit_id:
        return JSONResponse(status_code=422, content={"error": {"message": "audit_id requerido"}})
    text, redactions = redact_text(str(body.get("response_text") or ""))
    await audit_event({
        "audit_id": audit_id, "response_text": text, "redaction_count": redactions,
        "response_bytes": len(text.encode("utf-8")), "status_code": int(body.get("status_code") or 200),
        "duration_ms": float(body.get("duration_ms") or 0), "state": "completed",
        "properties": {"capture": "provider-dom", "finish_reason": body.get("finish_reason", "observed")},
    })
    return {"status": "ok", "audit_id": audit_id}


@app.post("/api/web-error")
async def web_error(request: Request):
    body = await request.json()
    audit_id = str(body.get("audit_id") or "")
    if not audit_id:
        return JSONResponse(status_code=422, content={"error": {"message": "audit_id requerido"}})
    await audit_event({
        "audit_id": audit_id, "state": "error", "error_type": str(body.get("error_type") or "web_send_error"),
        "error_message": str(body.get("error_message") or "El proveedor web no confirmó el envío")[:1000],
        "duration_ms": float(body.get("duration_ms") or 0),
    })
    return {"status": "ok", "audit_id": audit_id}


async def process_chat(body: dict[str, Any], *, source: str) -> JSONResponse | StreamingResponse:
    provider = str(body.get("provider", "chatgpt"))
    try:
        messages, redactions = sanitize_messages(body.get("messages", []))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": {"message": str(exc)}})
    audit_id = str(body.get("audit_id") or uuid.uuid4())
    model = choose_model(provider, body.get("model"))
    streaming = bool(body.get("stream", False))
    started = time.monotonic()
    payload = dict(body)
    payload.update({"model": model, "messages": messages, "stream": streaming})
    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = payload["metadata"] = {}
    metadata.update({"provider": provider, "source": source, "agent_redactions": redactions, "audit_id": audit_id})
    audit = audit_base(
        audit_id=audit_id, provider=provider, source=source, model=model, prompt=prompt_text(messages),
        redactions=redactions, streaming=streaming, started=time.time(), client=str(body.get("client") or source),
        conversation_id=str(body.get("conversation_id") or "") or None,
    )
    if streaming:
        return await build_stream_response("/v1/chat/completions", payload, audit, started)
    response = await forward_json("/v1/chat/completions", payload, audit, started)
    response.headers["x-agent-redactions"] = str(redactions)
    return response


@app.post("/api/chat")
async def api_chat(request: Request):
    return await process_chat(await request.json(), source="governed-desktop")


@app.post("/v1/chat/completions")
async def openai_compatible(request: Request):
    return await process_chat(await request.json(), source="governed-agent-openai-api")
