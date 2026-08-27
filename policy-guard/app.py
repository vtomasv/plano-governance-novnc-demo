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
import re
import time
import unicodedata
from collections import Counter, deque
from typing import Any, Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

POLICY_MESSAGE = "No es posible realizar preguntas sobre el presidente de Argentina."
DATA_LOSS_MESSAGE = "La solicitud fue bloqueada para prevenir una posible fuga de datos sensibles."
LOG_PROMPT_BODIES = os.getenv("LOG_PROMPT_BODIES", "false").lower() == "true"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [POLICY_GUARD] %(levelname)s %(message)s",
)
logger = logging.getLogger("policy_guard")

app = FastAPI(title="Plano Governance Policy Guard", version="1.0.0")
COUNTERS: Counter[str] = Counter()
RECENT_DECISIONS: deque[dict[str, Any]] = deque(maxlen=100)

PRESIDENT_TERMS = {
    "presidente",
    "presidenta",
    "presidencia",
    "presidential",
    "president",
    "mandatario",
    "mandataria",
    "jefe de estado",
    "head of state",
}
ARGENTINA_TERMS = {"argentina", "argentino", "argentina's", "casa rosada"}
MILEI_ALIASES = {"milei", "miley", "mliey", "javier milei", "javier gerardo milei"}

SECRET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I)),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b", re.I)),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}\b", re.I)),
    (
        "assigned_secret",
        re.compile(
            r"\b(?:password|passwd|api[_ -]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}",
            re.I,
        ),
    ),
]


def normalize_text(value: str) -> str:
    """Normaliza Unicode, acentos, espacios y sustituciones leetspeak comunes."""
    value = unicodedata.normalize("NFKC", value)
    value = "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )
    value = value.casefold().translate(str.maketrans({"1": "i", "!": "i", "3": "e", "0": "o"}))
    value = re.sub(r"[^a-z0-9'\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def damerau_levenshtein_at_most_one(left: str, right: str) -> bool:
    """Detecta igualdad, una edición o una transposición; suficiente para Milei/Mliey/Miley."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        diffs = [idx for idx, (a, b) in enumerate(zip(left, right)) if a != b]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and left[diffs[0]] == right[diffs[1]]
            and left[diffs[1]] == right[diffs[0]]
        )
    short, long = (left, right) if len(left) < len(right) else (right, left)
    index_short = index_long = edits = 0
    while index_short < len(short) and index_long < len(long):
        if short[index_short] == long[index_long]:
            index_short += 1
            index_long += 1
        else:
            edits += 1
            index_long += 1
            if edits > 1:
                return False
    return True


def contains_milei_variant(normalized: str) -> bool:
    compact = re.sub(r"\s+", "", normalized)
    if any(re.sub(r"\s+", "", alias) in compact for alias in MILEI_ALIASES):
        return True
    words = re.findall(r"[a-z0-9]+", normalized)
    return any(4 <= len(word) <= 6 and damerau_levenshtein_at_most_one(word, "milei") for word in words)


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


def has_any_phrase(normalized: str, phrases: Iterable[str]) -> bool:
    return any(phrase in normalized for phrase in phrases)


def evaluate_policy(texts: list[str]) -> tuple[bool, str, str]:
    combined = "\n".join(texts)
    normalized = normalize_text(combined)

    has_president = has_any_phrase(normalized, PRESIDENT_TERMS)
    has_argentina = has_any_phrase(normalized, ARGENTINA_TERMS)
    has_milei = contains_milei_variant(normalized)

    if (has_president and has_argentina) or (has_president and has_milei):
        return False, "argentina_president", POLICY_MESSAGE

    for rule_name, pattern in SECRET_RULES:
        if pattern.search(combined):
            return False, rule_name, DATA_LOSS_MESSAGE

    return True, "allowed", "Solicitud permitida."


def record_decision(*, allowed: bool, rule: str, endpoint: str, provider: str, texts: list[str]) -> str:
    digest = hashlib.sha256("\n".join(texts).encode("utf-8", errors="replace")).hexdigest()[:16]
    decision_id = hashlib.sha256(f"{time.time_ns()}:{digest}".encode()).hexdigest()[:16]
    outcome = "allow" if allowed else "deny"
    COUNTERS[f"decision_{outcome}"] += 1
    COUNTERS[f"rule_{rule}"] += 1
    event = {
        "decision_id": decision_id,
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
    return decision_id


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
    allowed, rule, message = evaluate_policy(texts)
    decision_id = record_decision(
        allowed=allowed,
        rule=rule,
        endpoint=endpoint,
        provider=provider,
        texts=texts,
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
                }
            },
            headers={"x-plano-policy-decision": "deny", "x-plano-decision-id": decision_id},
        )

    if isinstance(body, dict):
        metadata = body.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["plano_policy_decision"] = "allow"
            metadata["plano_decision_id"] = decision_id
    return JSONResponse(
        status_code=200,
        content=body,
        headers={"x-plano-policy-decision": "allow", "x-plano-decision-id": decision_id},
    )


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
