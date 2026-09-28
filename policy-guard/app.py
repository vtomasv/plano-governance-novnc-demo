"""Filtro HTTP para Plano: gobierno de prompts y prevención de fuga de datos.

El servicio recibe el cuerpo completo que Plano está a punto de enviar al proveedor.
Devuelve HTTP 200 con el mismo cuerpo para permitir, o HTTP 403 para cortar el flujo.
No persiste el texto de los prompts: solo registra metadatos y una huella truncada.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.request
import uuid
from collections import Counter, deque
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from default_rules import DATA_LOSS_MESSAGE, POLICY_MESSAGE, default_rules
from engine import CompiledRule, compile_rule, compile_rules, evaluate, normalize_text, validate_rule

LOG_PROMPT_BODIES = os.getenv("LOG_PROMPT_BODIES", "false").lower() == "true"
AUDIT_URL = os.getenv("AUDIT_URL", "http://audit-dashboard:10700/ingest")
AUDIT_TOKEN = os.getenv("AUDIT_INGEST_TOKEN", "plano-audit-ingest-demo")
RULES_BASE_URL = os.getenv("RULES_BASE_URL", "http://audit-dashboard:10700")
RULES_POLL_SECONDS = max(1.0, float(os.getenv("RULES_POLL_SECONDS", "5")))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [POLICY_GUARD] %(levelname)s %(message)s",
)
logger = logging.getLogger("policy_guard")

app = FastAPI(title="Plano Governance Policy Guard", version="2.0.0")
COUNTERS: Counter[str] = Counter()
RECENT_DECISIONS: deque[dict[str, Any]] = deque(maxlen=100)


class RuleState:
    """Conjunto de reglas activo. El reemplazo es atómico: nunca hay estado a medias."""

    def __init__(self) -> None:
        self.rules: tuple[CompiledRule, ...] = compile_rules(default_rules())[0]
        self.revision = 0
        self.source = "builtin"
        self.errors: dict[str, str] = {}
        self.loaded_at = time.time()
        self.last_error = ""


STATE = RuleState()
REFRESH_LOCK = threading.Lock()


def apply_rules(rules: list[dict[str, Any]], revision: int, source: str) -> None:
    compiled, errors = compile_rules(rules)
    STATE.rules, STATE.errors = compiled, errors
    STATE.revision, STATE.source, STATE.loaded_at = revision, source, time.time()
    logger.info("Reglas aplicadas: revision=%s activas=%s invalidas=%s", revision, len(compiled), len(errors))


def _dashboard_call(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{RULES_BASE_URL}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method="GET" if payload is None else "POST",
        headers={"content-type": "application/json", "x-audit-token": AUDIT_TOKEN},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def refresh_rules(force: bool = False) -> bool:
    """Sincroniza con el dashboard. Ante error conserva las reglas vigentes."""
    with REFRESH_LOCK:
        try:
            data = _dashboard_call("/policy/rules")
            if data.get("needs_seed"):
                _dashboard_call("/policy/seed", {"rules": default_rules()})
                data = _dashboard_call("/policy/rules")
            STATE.last_error = ""
            if force or data["revision"] != STATE.revision or STATE.source != "dashboard":
                apply_rules(data["rules"], int(data["revision"]), "dashboard")
                return True
        except Exception as exc:  # el dashboard puede no estar disponible; se sigue con lo último válido
            STATE.last_error = f"{type(exc).__name__}: {exc}"[:300]
        return False


def _poll_loop() -> None:
    while True:
        refresh_rules()
        time.sleep(RULES_POLL_SECONDS)


def require_admin(request: Request) -> None:
    token = request.headers.get("x-audit-token", "")
    if not token or not secrets.compare_digest(token, AUDIT_TOKEN):
        raise HTTPException(status_code=403, detail="Token inválido")


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=_poll_loop, name="rules-poller", daemon=True).start()


def extract_user_texts(body: Any) -> list[str]:
    """Extrae todos los turnos de usuario de formatos OpenAI, Responses y Anthropic.

    También entiende envoltorios de la demo web (`prompt`, `query`, `conversation`) para
    que el proxy TLS pueda normalizar solicitudes de interfaces gráficas sin almacenar
    ni reenviar cookies a este servicio.
    """
    texts: list[str] = []
    if not isinstance(body, dict):
        return texts

    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            texts.extend(extract_content(message.get("content")))

    input_value = body.get("input")
    if isinstance(input_value, str):
        texts.append(input_value)
    elif isinstance(input_value, list):
        for item in input_value:
            if isinstance(item, dict):
                if item.get("role") in (None, "user"):
                    texts.extend(extract_content(item.get("content", item.get("text"))))
            elif isinstance(item, str):
                texts.append(item)

    for key in ("prompt", "query", "user_prompt"):
        value = body.get(key)
        if isinstance(value, str):
            texts.append(value)

    conversation = body.get("conversation")
    if isinstance(conversation, list):
        for turn in conversation:
            if isinstance(turn, dict) and turn.get("role") == "user":
                texts.extend(extract_content(turn.get("content", turn.get("text"))))

    return [text for text in texts if text and text.strip()]


def extract_content(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        result: list[str] = []
        for part in content:
            if isinstance(part, str):
                result.append(part)
            elif isinstance(part, dict):
                for key in ("text", "input_text", "content"):
                    if isinstance(part.get(key), str):
                        result.append(part[key])
                        break
        return result
    if isinstance(content, dict):
        return [str(content[key]) for key in ("text", "input_text") if isinstance(content.get(key), str)]
    return []


def evaluate_policy(texts: list[str]) -> tuple[bool, str, str, list[str]]:
    blocking, monitored = evaluate(STATE.rules, texts)
    if blocking is not None:
        return False, blocking.id, blocking.message, monitored
    return True, "allowed", "Solicitud permitida.", monitored


def audit_event(payload: dict[str, Any]) -> None:
    try:
        request = urllib.request.Request(
            AUDIT_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"content-type": "application/json", "x-audit-token": AUDIT_TOKEN},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read(256)
    except Exception:
        return


def record_decision(*, allowed: bool, rule: str, endpoint: str, provider: str, texts: list[str], body: dict[str, Any], message: str = "", monitored: list[str] | None = None) -> tuple[str, str]:
    digest = hashlib.sha256("\n".join(texts).encode("utf-8", errors="replace")).hexdigest()[:16]
    decision_id = hashlib.sha256(f"{time.time_ns()}:{digest}".encode()).hexdigest()[:16]
    metadata = body.get("metadata", {}) if isinstance(body.get("metadata"), dict) else {}
    audit_id = str(metadata.get("audit_id") or uuid.uuid4())
    outcome = "allow" if allowed else "deny"
    COUNTERS[f"decision_{outcome}"] += 1
    COUNTERS[f"rule_{rule}"] += 1
    event = {
        "decision_id": decision_id,
        "audit_id": audit_id,
        "timestamp": int(time.time()),
        "decision": outcome,
        "rule": rule,
        "endpoint": endpoint,
        "provider": provider,
        "prompt_sha256_16": digest,
    }
    if LOG_PROMPT_BODIES:
        event["prompt_debug"] = texts
    RECENT_DECISIONS.appendleft(event)
    logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    audit_payload: dict[str, Any] = {
        "audit_id": audit_id,
        "source": str(metadata.get("source") or "direct-plano"),
        "provider": str(metadata.get("provider") or provider),
        "model": str(body.get("model") or provider),
        "endpoint": endpoint,
        "prompt_text": "\n".join(texts),
        "decision": outcome,
        "filtered": not allowed,
        "rule": rule,
        "decision_id": decision_id,
        "policy_message": "Solicitud permitida por Plano." if allowed else message,
        "status_code": 200 if allowed else 403,
        "streaming": bool(body.get("stream", False)),
        "state": "authorized" if allowed else "blocked",
        "properties": {
            "filter": "policy_guard",
            "audit_phase": metadata.get("audit_phase"),
            "rules_revision": STATE.revision,
            "monitor_rules": ",".join(monitored or []) or None,
        },
    }
    if metadata.get("client"):
        audit_payload["client"] = str(metadata["client"])
    audit_event(audit_payload)
    return decision_id, audit_id


@app.post("/admin/reload")
async def admin_reload(request: Request) -> dict[str, Any]:
    """El dashboard llama aquí tras cada cambio para aplicar la regla de inmediato."""
    require_admin(request)
    refresh_rules(force=True)
    return admin_state()


@app.get("/admin/status")
async def admin_status(request: Request) -> dict[str, Any]:
    require_admin(request)
    return admin_state()


@app.post("/admin/test")
async def admin_test(request: Request) -> dict[str, Any]:
    """Prueba un texto contra las reglas activas o contra una regla en borrador, sin registrar nada."""
    require_admin(request)
    payload = await request.json()
    text = str(payload.get("text") or "")[:20000]
    draft = payload.get("rule")
    if draft is not None:
        errors = validate_rule(draft)
        if errors:
            return {"valid": False, "errors": errors}
        rules: tuple[CompiledRule, ...] = (compile_rule({**draft, "enabled": True}),)
    else:
        rules = STATE.rules
    blocking, monitored = evaluate(rules, [text])
    return {
        "valid": True,
        "allowed": blocking is None,
        "rule": blocking.id if blocking else None,
        "message": blocking.message if blocking else None,
        "monitored": monitored,
        "normalized": normalize_text(text)[:500],
    }


def admin_state() -> dict[str, Any]:
    return {
        "revision": STATE.revision,
        "source": STATE.source,
        "active_rules": len(STATE.rules),
        "invalid_rules": STATE.errors,
        "loaded_at": STATE.loaded_at,
        "last_sync_error": STATE.last_error,
    }


@app.post("/{path:path}")
async def guard(path: str, request: Request):
    endpoint = f"/{path}"
    try:
        body = await request.json()
    except Exception:
        COUNTERS["invalid_json"] += 1
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "invalid_json", "message": "El cuerpo debe ser JSON válido."}},
        )

    texts = extract_user_texts(body)
    provider = str(body.get("metadata", {}).get("provider", body.get("model", "unknown"))) if isinstance(body, dict) else "unknown"
    allowed, rule, message, monitored = evaluate_policy(texts)
    decision_id, audit_id = record_decision(
        allowed=allowed,
        rule=rule,
        endpoint=endpoint,
        provider=provider,
        texts=texts,
        body=body,
        message=message,
        monitored=monitored,
    )

    if not allowed:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "type": "policy_violation",
                    "code": rule,
                    "message": message,
                    "decision_id": decision_id,
                    "audit_id": audit_id,
                }
            },
            headers={"x-plano-policy-decision": "deny", "x-plano-decision-id": decision_id, "x-plano-rules-revision": str(STATE.revision)},
        )

    if isinstance(body, dict):
        metadata = body.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["plano_policy_decision"] = "allow"
            metadata["plano_decision_id"] = decision_id
            metadata["audit_id"] = audit_id
    return JSONResponse(
        status_code=200,
        content=body,
        headers={"x-plano-policy-decision": "allow", "x-plano-decision-id": decision_id, "x-plano-rules-revision": str(STATE.revision)},
    )


@app.get("/")
async def index() -> dict[str, Any]:
    return {
        "service": "policy-guard",
        "purpose": "Filtro de entrada de Plano para gobierno y prevención de fuga de datos",
        "health": "/health",
        "decisions": "/decisions",
        "metrics": "/metrics",
        "configuration": "Reglas editables desde el dashboard de auditoría (/rules); recarga inmediata",
        "rules_revision": STATE.revision,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "policy-guard"}


@app.get("/decisions")
async def decisions() -> dict[str, Any]:
    return {"counters": dict(COUNTERS), "recent": list(RECENT_DECISIONS)}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    lines = ["# TYPE plano_policy_decisions_total counter"]
    for key, value in sorted(COUNTERS.items()):
        lines.append(f'plano_policy_decisions_total{{kind="{key}"}} {value}')
    return "\n".join(lines) + "\n"
