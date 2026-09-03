"""Addon mitmproxy para intercepción TLS controlada y decisión central en Plano.

La CA privada solo se usa dentro de la red Docker. El addon no registra cuerpos ni
cookies; normaliza el contenido de conversación y pide una decisión al listener de
Plano. Si Plano rechaza o no está disponible, la solicitud sensible no sale.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from mitmproxy import ctx, http

PLANO_URL = os.getenv("PLANO_POLICY_URL", "http://plano:12000/v1/chat/completions")
AUDIT_BASE_URL = os.getenv("AUDIT_BASE_URL", "http://audit-dashboard:10700")
AUDIT_TOKEN = os.getenv("AUDIT_INGEST_TOKEN", "plano-audit-ingest-demo")
FAIL_MODE = os.getenv("POLICY_FAIL_MODE", "closed").casefold()
MAX_BODY_BYTES = int(os.getenv("MAX_INSPECTION_BODY_BYTES", "2097152"))
BLOCK_MESSAGE = "No es posible realizar preguntas sobre el presidente de Argentina."

GOVERNED_HOST_SUFFIXES = tuple(
    item.strip().casefold()
    for item in os.getenv(
        "GOVERNED_HOSTS",
        "chatgpt.com,chat.openai.com,api.openai.com,claude.ai,api.anthropic.com,grok.com,x.com,api.x.ai,gemini.google.com,bard.google.com,generativelanguage.googleapis.com,chatgpt.demo.local,claude.demo.local,grok.demo.local,gemini.demo.local",
    ).split(",")
    if item.strip()
)

PROMPT_PATH_HINTS = re.compile(
    r"(?:conversation|completion|completions|messages|responses|chat|prompt|generate)", re.I
)
SENSITIVE_FIELD_HINTS = re.compile(
    r"(?:prompt|message|messages|content|text|input|query|parts|conversation)", re.I
)
EXCLUDED_FIELD_HINTS = re.compile(
    r"(?:cookie|authorization|credential|session|csrf|device|fingerprint|telemetry|analytics)", re.I
)


def governed_host(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    return any(normalized == suffix or normalized.endswith(f".{suffix}") for suffix in GOVERNED_HOST_SUFFIXES)


def provider_for_host(host: str) -> tuple[str, str]:
    lowered = host.casefold()
    if "claude" in lowered or "anthropic" in lowered:
        return "claude", "custom/local-claude"
    if "grok" in lowered or lowered == "x.com" or lowered.endswith(".x.com") or "api.x.ai" in lowered:
        return "grok", "custom/local-grok"
    if "gemini" in lowered or "bard" in lowered or "generativelanguage" in lowered:
        return "gemini", "custom/local-gemini"
    return "chatgpt", "custom/local-chatgpt"


def collect_strings(value: Any, *, key: str = "", depth: int = 0) -> list[str]:
    if depth > 12 or EXCLUDED_FIELD_HINTS.search(key):
        return []
    if isinstance(value, str):
        return [value] if (not key or SENSITIVE_FIELD_HINTS.search(key)) else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(collect_strings(item, key=key, depth=depth + 1))
        return result
    if isinstance(value, dict):
        result = []
        for child_key, child in value.items():
            result.extend(collect_strings(child, key=str(child_key), depth=depth + 1))
        return result
    return []


def extract_prompt(flow: http.HTTPFlow) -> tuple[str | None, str]:
    request = flow.request
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return None, "not_mutating"
    if not PROMPT_PATH_HINTS.search(request.path) and not request.host.casefold().endswith(".demo.local"):
        return None, "path_not_prompt_like"
    raw = request.raw_content or b""
    if not raw:
        return None, "empty_body"
    if len(raw) > MAX_BODY_BYTES:
        return None, "body_too_large"

    content_type = request.headers.get("content-type", "").casefold()
    try:
        if "json" in content_type or raw.lstrip().startswith((b"{", b"[")):
            parsed = json.loads(request.get_text(strict=False))
            strings = collect_strings(parsed)
            text = "\n".join(item for item in strings if item.strip())
            return (text or None), "json"
        if "application/x-www-form-urlencoded" in content_type or content_type.startswith("text/"):
            text = request.get_text(strict=False)
            return (text or None), "text"
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None, "decode_error"
    return None, "opaque_body"


def audit_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        request = urllib.request.Request(
            f"{AUDIT_BASE_URL}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"content-type": "application/json", "x-audit-token": AUDIT_TOKEN},
        )
        with urllib.request.urlopen(request, timeout=2.5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def correlate_audit(prompt: str, provider: str) -> str:
    result = audit_post("/correlate", {"prompt_text": prompt, "provider": provider})
    return str(result.get("audit_id") or uuid.uuid4())


def response_content(flow: http.HTTPFlow) -> str:
    response = flow.response
    if response is None or not response.raw_content:
        return ""
    raw = response.raw_content[:262144]
    content_type = response.headers.get("content-type", "").casefold()
    try:
        text = response.get_text(strict=False)
    except Exception:
        text = raw.decode("utf-8", errors="replace")
    text = text[:50000]
    if "json" in content_type:
        try:
            parsed = json.loads(text)
            strings = collect_strings(parsed)
            clean = "\n".join(value for value in strings if value.strip())
            return clean[:50000] or text
        except ValueError:
            return text
    return text


def plano_decision(*, prompt: str, provider: str, host: str, path: str, audit_id: str) -> tuple[bool, str, str]:
    payload = {
        "model": provider_for_host(host)[1],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "metadata": {
            "provider": provider,
            "source": "tls-interceptor",
            "target_host": host,
            "target_path": path[:512],
            "audit_id": audit_id,
            "audit_phase": "tls-preflight",
            "client": f"{provider}-free-web" if not host.endswith(".demo.local") else "tls-demo",
        },
    }
    request = urllib.request.Request(
        PLANO_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json", "x-plano-demo-source": "tls-interceptor"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
            decision_id = (
                body.get("choices", [{}])[0].get("message", {}).get("metadata", {}).get("plano_decision_id")
                if isinstance(body, dict)
                else None
            ) or response.headers.get("x-plano-decision-id", "not-returned")
            return True, "Solicitud permitida por Plano.", str(decision_id)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
            detail = body.get("error", body.get("detail", {})) if isinstance(body, dict) else {}
            if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
                detail = detail["error"]
            message = detail.get("message", BLOCK_MESSAGE) if isinstance(detail, dict) else BLOCK_MESSAGE
            decision_id = detail.get("decision_id", "not-returned") if isinstance(detail, dict) else "not-returned"
        except ValueError:
            message, decision_id = BLOCK_MESSAGE, "not-returned"
        return False, str(message), str(decision_id)
    except Exception as exc:
        if FAIL_MODE == "open":
            return True, f"Plano no disponible; fail-open: {type(exc).__name__}", "unavailable"
        return False, "Plano no está disponible; la solicitud fue bloqueada en modo cerrado.", "unavailable"


def deny(flow: http.HTTPFlow, message: str, decision_id: str, reason: str) -> None:
    body = {
        "error": {
            "type": "policy_violation",
            "code": reason,
            "message": message,
            "decision_id": decision_id,
        }
    }
    flow.response = http.Response.make(
        403,
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
        {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
            "x-plano-policy-decision": "deny",
            "x-plano-decision-id": decision_id,
        },
    )


class PlanoGovernanceAddon:
    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        if not governed_host(host):
            return

        prompt, parse_status = extract_prompt(flow)
        likely_prompt = bool(PROMPT_PATH_HINTS.search(flow.request.path))
        if prompt is None:
            if likely_prompt and parse_status in {"body_too_large", "decode_error", "opaque_body"}:
                deny(
                    flow,
                    "Plano no pudo inspeccionar el cuerpo de la solicitud; envío bloqueado en modo cerrado.",
                    "not-created",
                    f"inspection_{parse_status}",
                )
            return

        provider, _model = provider_for_host(host)
        audit_id = correlate_audit(prompt, provider)
        started = time.monotonic()
        audit_post("/ingest", {
            "audit_id": audit_id,
            "source": "tls-interceptor",
            "client": f"{provider}-free-web" if not host.endswith(".demo.local") else "tls-demo",
            "provider": provider,
            "model": provider_for_host(host)[1],
            "target_host": host,
            "target_path": flow.request.path[:512],
            "endpoint": flow.request.path[:512],
            "prompt_text": prompt,
            "request_bytes": len(flow.request.raw_content or b""),
            "streaming": "stream" in flow.request.path.casefold() or "text/event-stream" in flow.request.headers.get("accept", "").casefold(),
            "state": "evaluating",
            "properties": {"capture": "mitmproxy", "parse_status": parse_status},
        })
        allowed, message, decision_id = plano_decision(
            prompt=prompt,
            provider=provider,
            host=host,
            path=flow.request.path,
            audit_id=audit_id,
        )
        event = {
            "timestamp": int(time.time()),
            "host": host,
            "path": flow.request.path[:256],
            "provider": provider,
            "decision": "allow" if allowed else "deny",
            "decision_id": decision_id,
            "audit_id": audit_id,
            "prompt_sha256_16": hashlib.sha256(prompt.encode("utf-8", errors="replace")).hexdigest()[:16],
        }
        ctx.log.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        event["started_monotonic"] = started
        flow.metadata["plano_policy"] = event
        audit_post("/ingest", {
            "audit_id": audit_id,
            "decision": "allow" if allowed else "deny",
            "filtered": not allowed,
            "rule": "allowed" if allowed else "argentina_president_or_dlp",
            "decision_id": decision_id,
            "policy_message": message,
            "status_code": 200 if allowed else 403,
            "state": "authorized" if allowed else "blocked",
        })
        if not allowed:
            deny(flow, message, decision_id, "argentina_president_or_dlp")

    def response(self, flow: http.HTTPFlow) -> None:
        event = flow.metadata.get("plano_policy")
        if not isinstance(event, dict) or event.get("decision") != "allow" or flow.response is None:
            return
        text = response_content(flow)
        started = float(event.get("started_monotonic") or time.monotonic())
        status = int(flow.response.status_code)
        audit_post("/ingest", {
            "audit_id": event.get("audit_id"),
            "response_text": text,
            "response_bytes": len(flow.response.raw_content or b""),
            "status_code": status,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "decision": "allow",
            "filtered": False,
            "rule": "allowed",
            "state": "completed" if status < 400 else "error",
            "properties": {"response_capture": "mitmproxy", "content_type": flow.response.headers.get("content-type", "")[:160]},
        })


addons = [PlanoGovernanceAddon()]
