"""Dashboard local de auditoría para solicitudes LLM gobernadas por Plano."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse

import analytics
import rules_store

DATA_DIR = Path(os.getenv("AUDIT_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "audit.db"
STATIC_DIR = Path(__file__).parent / "static"
INGEST_TOKEN = os.getenv("AUDIT_INGEST_TOKEN", "plano-audit-ingest-demo")
DASHBOARD_USER = os.getenv("AUDIT_DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD = os.getenv("AUDIT_DASHBOARD_PASSWORD", "plano-demo")
RETENTION_DAYS = max(1, int(os.getenv("AUDIT_RETENTION_DAYS", "7")))
MAX_EVENTS = max(100, int(os.getenv("AUDIT_MAX_EVENTS", "10000")))
MAX_TEXT_CHARS = max(1000, int(os.getenv("AUDIT_MAX_TEXT_CHARS", "50000")))
GUARD_URL = os.getenv("POLICY_GUARD_URL", "http://policy-guard:10500").rstrip("/")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host-publisher:11434")
ANALYTICS_MODEL = os.getenv("ANALYTICS_MODEL", "qwen2.5:7b-instruct")
ANALYTICS_ENABLED = os.getenv("ANALYTICS_ENABLED", "true").lower() == "true"
ANALYTICS_IDLE_SECONDS = float(os.getenv("ANALYTICS_IDLE_SECONDS", "3"))
ANALYTICS_BACKOFF_SECONDS = float(os.getenv("ANALYTICS_BACKOFF_SECONDS", "30"))
DB_LOCK = threading.RLock()
NO_STORE = {"Cache-Control": "no-store"}
ANALYTICS_STATE: dict[str, Any] = {"worker": "stopped", "last_result": None, "last_at": None}
STARTED_AT = time.time()

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I | re.S),
    re.compile(r"\bsk-(?:proj-|svcacct-|ant-)?[A-Za-z0-9_-]{16,}\b", re.I),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.I),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|cookie|session)[\s\"']*[:=][\s\"']*[^\s,;\"']{6,}"),
]

TOPIC_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("gobierno_y_politica", ("presidente", "gobierno", "eleccion", "argentina", "milei", "milei", "politica", "ministerio", "congreso")),
    ("seguridad_y_datos", ("api key", "token", "secreto", "credencial", "password", "seguridad", "fuga", "dlp", "pii", "privacidad")),
    ("programacion", ("codigo", "python", "javascript", "typescript", "docker", "kubernetes", "api", "sql", "bug", "funcion")),
    ("ciencia_y_educacion", ("ciencia", "fisica", "quimica", "biologia", "matematica", "explica", "estudia", "fotosintesis")),
    ("finanzas", ("finanza", "inversion", "accion", "bono", "precio", "mercado", "banco", "credito", "presupuesto")),
    ("soporte_al_cliente", ("cliente", "soporte", "ticket", "incidente", "reclamo", "devolucion", "pedido", "servicio")),
    ("salud", ("salud", "medico", "sintoma", "diagnostico", "tratamiento", "medicamento", "hospital")),
    ("redaccion_y_traduccion", ("redacta", "resume", "traduce", "traduccion", "correo", "documento", "reescribe", "gramatica")),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    conversation_id TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    duration_ms REAL,
    source TEXT,
    client TEXT,
    provider TEXT,
    model TEXT,
    target_host TEXT,
    target_path TEXT,
    endpoint TEXT,
    topic TEXT,
    topic_confidence REAL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    prompt_text TEXT,
    prompt_sha256 TEXT,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    response_text TEXT,
    response_chars INTEGER NOT NULL DEFAULT 0,
    decision TEXT,
    filtered INTEGER NOT NULL DEFAULT 0,
    rule TEXT,
    decision_id TEXT,
    policy_message TEXT,
    redaction_count INTEGER NOT NULL DEFAULT 0,
    status_code INTEGER,
    streaming INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    request_bytes INTEGER,
    response_bytes INTEGER,
    state TEXT NOT NULL DEFAULT 'pending',
    error_type TEXT,
    error_message TEXT,
    properties_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_started ON audit_events(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_topic ON audit_events(topic, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_provider ON audit_events(provider, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_decision ON audit_events(decision, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_source ON audit_events(source, started_at DESC);
"""

TEXT_FIELDS = {"source", "client", "provider", "model", "target_host", "target_path", "endpoint", "decision", "rule", "decision_id", "policy_message", "state", "error_type", "error_message", "conversation_id"}
NUMERIC_FIELDS = {"duration_ms", "status_code", "request_bytes", "response_bytes", "tool_calls"}
BOOL_FIELDS = {"filtered", "streaming"}

app = FastAPI(title="Plano LLM Audit Dashboard", version="1.0.0")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def redact(value: Any) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    value = value[:MAX_TEXT_CHARS]
    count = 0
    for pattern in SECRET_PATTERNS:
        value, changes = pattern.subn("[REDACTED_BY_AUDIT]", value)
        count += changes
    return value, count


def normalized(value: str) -> str:
    import unicodedata

    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(char))


def classify_topic(prompt: str | None) -> tuple[str, float]:
    if not prompt:
        return "general", 0.0
    text = normalized(prompt)
    scores = [(topic, sum(1 for term in terms if normalized(term) in text)) for topic, terms in TOPIC_RULES]
    topic, score = max(scores, key=lambda item: item[1])
    if score <= 0:
        return "general", 0.25
    return topic, min(0.98, 0.5 + score * 0.12)


def basic_authorized(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
        user, password = decoded.split(":", 1)
    except Exception:
        return False
    return secrets.compare_digest(user, DASHBOARD_USER) and secrets.compare_digest(password, DASHBOARD_PASSWORD)


def require_dashboard(request: Request) -> None:
    if not basic_authorized(request):
        raise HTTPException(status_code=401, detail="Autenticación requerida", headers={"WWW-Authenticate": 'Basic realm="Plano Audit Dashboard"'})


def require_ingest(request: Request) -> None:
    token = request.headers.get("x-audit-token", "")
    if not token or not secrets.compare_digest(token, INGEST_TOKEN):
        raise HTTPException(status_code=403, detail="Token de ingesta inválido")


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with DB_LOCK, db() as connection:
        connection.executescript(SCHEMA)
        rules_store.init(connection)
        analytics.init(connection)


def purge_retention(connection: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    connection.execute("DELETE FROM audit_events WHERE started_at < ?", (cutoff,))
    connection.execute(
        "DELETE FROM audit_events WHERE audit_id IN (SELECT audit_id FROM audit_events ORDER BY started_at DESC LIMIT -1 OFFSET ?)",
        (MAX_EVENTS,),
    )
    connection.execute("DELETE FROM event_analysis WHERE audit_id NOT IN (SELECT audit_id FROM audit_events)")


def row_to_dict(row: sqlite3.Row, *, detail: bool = True) -> dict[str, Any]:
    item = dict(row)
    item["filtered"] = bool(item["filtered"])
    item["streaming"] = bool(item["streaming"])
    for key in ("tags_json", "properties_json"):
        target = "tags" if key == "tags_json" else "properties"
        try:
            item[target] = json.loads(item.pop(key) or ("[]" if target == "tags" else "{}"))
        except ValueError:
            item[target] = [] if target == "tags" else {}
    if not detail:
        prompt = item.pop("prompt_text", None)
        response = item.pop("response_text", None)
        item["prompt_preview"] = (prompt or "")[:240]
        item["response_preview"] = (response or "")[:240]
    return item


def clean_properties(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    blocked = re.compile(r"authorization|cookie|password|credential|secret|token", re.I)
    result: dict[str, Any] = {}
    for key, item in list(value.items())[:64]:
        if blocked.search(str(key)):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            text, _ = redact(item) if isinstance(item, str) else (item, 0)
            result[str(key)[:80]] = text
    return result


def upsert_event(payload: dict[str, Any]) -> dict[str, Any]:
    audit_id = str(payload.get("audit_id") or uuid.uuid4())[:80]
    now = utc_now()
    values: dict[str, Any] = {
        "audit_id": audit_id,
        "started_at": str(payload.get("started_at") or now),
        "updated_at": now,
    }
    total_new_redactions = int(payload.get("redaction_count") or 0)
    if "prompt_text" in payload:
        prompt, prompt_redactions = redact(payload.get("prompt_text"))
        topic, confidence = classify_topic(prompt)
        values.update({
            "prompt_text": prompt,
            "prompt_sha256": hashlib.sha256((prompt or "").encode()).hexdigest(),
            "prompt_chars": len(prompt or ""),
            "topic": topic,
            "topic_confidence": confidence,
        })
        total_new_redactions += prompt_redactions
    if "response_text" in payload:
        response, response_redactions = redact(payload.get("response_text"))
        values.update({"response_text": response, "response_chars": len(response or "")})
        total_new_redactions += response_redactions
    supplied_topic = str(payload.get("topic") or "").strip()
    if supplied_topic:
        values["topic"] = supplied_topic[:80]
        values["topic_confidence"] = float(payload.get("topic_confidence", 1.0))
    if total_new_redactions or "redaction_count" in payload:
        values["redaction_count"] = total_new_redactions
    if "tags" in payload:
        values["tags_json"] = json.dumps(payload.get("tags") if isinstance(payload.get("tags"), list) else [], ensure_ascii=False)
    if "properties" in payload:
        values["properties_json"] = json.dumps(clean_properties(payload.get("properties")), ensure_ascii=False)
    for key in TEXT_FIELDS:
        if key in payload and payload[key] is not None:
            values[key] = str(payload[key])[:2000]
    for key in NUMERIC_FIELDS:
        if key in payload and payload[key] is not None:
            values[key] = float(payload[key]) if key == "duration_ms" else int(payload[key])
    for key in BOOL_FIELDS:
        if key in payload and payload[key] is not None:
            values[key] = 1 if bool(payload[key]) else 0

    decision = values.get("decision")
    if decision in {"deny", "blocked"}:
        values["filtered"] = 1
        values["state"] = "blocked"
        values.setdefault("completed_at", now)
    if payload.get("completed_at") is not None:
        values["completed_at"] = str(payload["completed_at"])
    elif values.get("state") in {"completed", "blocked", "error"}:
        values["completed_at"] = now

    columns = list(values)
    placeholders = ",".join("?" for _ in columns)
    updates = [column for column in columns if column not in {"audit_id", "started_at"}]
    update_sql = ",".join(f"{column}=excluded.{column}" for column in updates)
    with DB_LOCK, db() as connection:
        connection.execute(
            f"INSERT INTO audit_events ({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(audit_id) DO UPDATE SET {update_sql}",
            tuple(values[column] for column in columns),
        )
        purge_retention(connection)
        row = connection.execute("SELECT * FROM audit_events WHERE audit_id=?", (audit_id,)).fetchone()
    return row_to_dict(row)


def analytics_worker() -> None:
    """Clasifica prompts pendientes uno a uno; Ollama procesa una petición a la vez."""
    ANALYTICS_STATE["worker"] = "running"
    while True:
        try:
            outcome = analytics.analyze_one(db, OLLAMA_URL, ANALYTICS_MODEL)
        except Exception as exc:  # el worker nunca debe morir
            outcome = "unavailable"
            ANALYTICS_STATE["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        ANALYTICS_STATE.update(last_result=outcome, last_at=utc_now())
        if outcome in {"done", "error"}:
            continue
        time.sleep(ANALYTICS_BACKOFF_SECONDS if outcome == "unavailable" else ANALYTICS_IDLE_SECONDS)


@app.on_event("startup")
def startup() -> None:
    init_db()
    if ANALYTICS_ENABLED:
        threading.Thread(target=analytics_worker, name="analytics-worker", daemon=True).start()


@app.get("/health")
def health() -> dict[str, Any]:
    init_db()
    with db() as connection:
        total = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    return {"status": "healthy", "service": "audit-dashboard", "events": total, "uptime_seconds": int(time.time() - STARTED_AT)}


@app.post("/correlate")
async def correlate(request: Request) -> dict[str, Any]:
    require_ingest(request)
    payload = await request.json()
    prompt, _ = redact(payload.get("prompt_text") if isinstance(payload, dict) else "")
    provider = str(payload.get("provider") or "unknown") if isinstance(payload, dict) else "unknown"
    digest = hashlib.sha256((prompt or "").encode()).hexdigest()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=180)).isoformat()
    with db() as connection:
        row = connection.execute(
            """SELECT audit_id FROM audit_events
               WHERE provider=? AND prompt_sha256=? AND started_at>=?
                 AND state IN ('evaluating','authorized','pending')
               ORDER BY started_at DESC LIMIT 1""",
            (provider, digest, cutoff),
        ).fetchone()
    return {"audit_id": row["audit_id"] if row else str(uuid.uuid4()), "matched": bool(row)}


@app.post("/ingest")
async def ingest(request: Request) -> dict[str, Any]:
    require_ingest(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="El evento debe ser un objeto JSON")
    item = upsert_event(payload)
    return {"status": "ok", "audit_id": item["audit_id"], "topic": item["topic"], "state": item["state"]}


@app.get("/")
def index(request: Request) -> FileResponse:
    require_dashboard(request)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def api_config(request: Request) -> dict[str, Any]:
    require_dashboard(request)
    return {
        "retention_days": RETENTION_DAYS,
        "max_events": MAX_EVENTS,
        "max_text_chars": MAX_TEXT_CHARS,
        "content_storage": True,
        "redaction": True,
        "database": str(DB_PATH),
    }


@app.get("/api/events")
def list_events(
    request: Request,
    search: str = "",
    topic: str = "",
    provider: str = "",
    decision: str = "",
    source: str = "",
    state: str = "",
    hours: int = Query(168, ge=1, le=8760),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    require_dashboard(request)
    clauses = ["started_at >= ?"]
    params: list[Any] = [(datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()]
    for column, value in (("topic", topic), ("provider", provider), ("decision", decision), ("source", source), ("state", state)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if search:
        clauses.append("(prompt_text LIKE ? OR response_text LIKE ? OR model LIKE ? OR rule LIKE ? OR audit_id LIKE ?)")
        needle = f"%{search[:200]}%"
        params.extend([needle] * 5)
    where = " AND ".join(clauses)
    with db() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM audit_events WHERE {where}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM audit_events WHERE {where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return {"total": total, "limit": limit, "offset": offset, "items": [row_to_dict(row, detail=False) for row in rows]}


@app.get("/api/events/{audit_id}")
def event_detail(audit_id: str, request: Request) -> dict[str, Any]:
    require_dashboard(request)
    with db() as connection:
        row = connection.execute("SELECT * FROM audit_events WHERE audit_id=?", (audit_id,)).fetchone()
        analysis = connection.execute("SELECT * FROM event_analysis WHERE audit_id=?", (audit_id,)).fetchone() if row else None
    if row is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    item = row_to_dict(row)
    item["analysis"] = dict(analysis) if analysis else None
    return item


@app.get("/api/summary")
def summary(request: Request, hours: int = Query(168, ge=1, le=8760)) -> dict[str, Any]:
    require_dashboard(request)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db() as connection:
        aggregate = dict(connection.execute(
            """SELECT COUNT(*) total,
               SUM(CASE WHEN decision='allow' THEN 1 ELSE 0 END) allowed,
               SUM(CASE WHEN decision IN ('deny','blocked') THEN 1 ELSE 0 END) denied,
               SUM(filtered) filtered,
               SUM(CASE WHEN state='error' THEN 1 ELSE 0 END) errors,
               AVG(duration_ms) avg_duration_ms
               FROM audit_events WHERE started_at >= ?""",
            (cutoff,),
        ).fetchone())
        groups: dict[str, list[dict[str, Any]]] = {}
        for column in ("topic", "provider", "decision", "source", "state"):
            rows = connection.execute(
                f"SELECT COALESCE({column}, 'unknown') name, COUNT(*) count FROM audit_events WHERE started_at >= ? GROUP BY {column} ORDER BY count DESC",
                (cutoff,),
            ).fetchall()
            groups[column] = [dict(row) for row in rows]
        timeline = [dict(row) for row in connection.execute(
            "SELECT substr(started_at,1,13) bucket, COUNT(*) total, SUM(filtered) filtered FROM audit_events WHERE started_at >= ? GROUP BY bucket ORDER BY bucket",
            (cutoff,),
        ).fetchall()]
    aggregate["avg_duration_ms"] = round(aggregate.get("avg_duration_ms") or 0, 1)
    for key in ("allowed", "denied", "filtered", "errors"):
        aggregate[key] = int(aggregate.get(key) or 0)
    return {"hours": hours, "aggregate": aggregate, "groups": groups, "timeline": timeline}


@app.get("/api/export.csv")
def export_csv(request: Request, hours: int = Query(168, ge=1, le=8760)) -> StreamingResponse:
    require_dashboard(request)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db() as connection:
        rows = connection.execute("SELECT * FROM audit_events WHERE started_at >= ? ORDER BY started_at DESC", (cutoff,)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    with db() as connection:
        headers = [column[1] for column in connection.execute("PRAGMA table_info(audit_events)").fetchall()]
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row[header] for header in headers])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=plano-audit.csv"})


@app.delete("/api/events")
def delete_events(request: Request) -> JSONResponse:
    require_dashboard(request)
    with DB_LOCK, db() as connection:
        deleted = connection.execute("DELETE FROM audit_events").rowcount
        connection.execute("DELETE FROM event_analysis")
    return JSONResponse({"status": "ok", "deleted": deleted})


# --- Gestión de reglas ------------------------------------------------------------------


class GuardUnavailable(Exception):
    pass


def guard_request(path: str, payload: dict[str, Any] | None = None, method: str = "POST", timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{GUARD_URL}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method=method,
        headers={"content-type": "application/json", "x-audit-token": INGEST_TOKEN},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except Exception as exc:
        raise GuardUnavailable(f"{type(exc).__name__}: {exc}"[:200]) from exc


def validate_with_guard(rule: dict[str, Any]) -> None:
    """El policy-guard es quien ejecuta las reglas, así que es quien decide si una regla es válida."""
    try:
        result = guard_request("/admin/test", {"rule": rule, "text": ""})
    except GuardUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo validar: policy-guard no responde ({exc})")
    if not result.get("valid"):
        raise HTTPException(status_code=422, detail={"errors": result.get("errors", [])})


def push_to_guard(revision: int) -> dict[str, Any]:
    """Aplica la regla de inmediato. Si falla, el guard la tomará por sondeo en pocos segundos."""
    try:
        state = guard_request("/admin/reload")
        return {"applied": state.get("revision") == revision, "guard": state}
    except GuardUnavailable as exc:
        return {"applied": False, "guard": None, "warning": f"policy-guard no respondió; se sincronizará por sondeo ({exc})"}


@app.get("/policy/rules")
def policy_rules(request: Request) -> dict[str, Any]:
    require_ingest(request)
    with db() as connection:
        return {
            "revision": rules_store.revision(connection),
            "needs_seed": rules_store.needs_seed(connection),
            "rules": rules_store.list_rules(connection),
        }


@app.post("/policy/seed")
async def policy_seed(request: Request) -> dict[str, Any]:
    require_ingest(request)
    payload = await request.json()
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        raise HTTPException(status_code=422, detail="Se esperaba {'rules': [...]}")
    with DB_LOCK, db() as connection:
        return {"revision": rules_store.seed(connection, rules)}


@app.get("/rules")
def rules_page(request: Request) -> FileResponse:
    require_dashboard(request)
    return FileResponse(STATIC_DIR / "rules.html", headers=NO_STORE)


@app.get("/api/rules")
def api_list_rules(request: Request) -> dict[str, Any]:
    require_dashboard(request)
    with db() as connection:
        rules = rules_store.list_rules(connection)
        revision = rules_store.revision(connection)
    try:
        guard = guard_request("/admin/status", method="GET", timeout=3)
    except GuardUnavailable as exc:
        guard = {"error": str(exc)}
    return {"revision": revision, "rules": rules, "guard": guard}


def _save(rule: dict[str, Any], actor: str) -> dict[str, Any]:
    # Bloqueante a propósito: debe ejecutarse en un threadpool. El guard, al recargar, vuelve a
    # llamar a /policy/rules; si esto corriera en el event loop, esa llamada quedaría bloqueada.
    validate_with_guard(rule)
    with DB_LOCK, db() as connection:
        saved, revision = rules_store.save_rule(connection, rule, actor)
    return {"rule": saved, "revision": revision, **push_to_guard(revision)}


@app.post("/api/rules")
async def api_create_rule(request: Request) -> dict[str, Any]:
    require_dashboard(request)
    rule = await request.json()
    if not isinstance(rule, dict):
        raise HTTPException(status_code=422, detail="La regla debe ser un objeto JSON")
    with db() as connection:
        if rules_store.get_rule(connection, str(rule.get("id"))):
            raise HTTPException(status_code=409, detail="Ya existe una regla con ese id")
    return await run_in_threadpool(_save, rule, DASHBOARD_USER)


@app.put("/api/rules/{rule_id}")
async def api_update_rule(rule_id: str, request: Request) -> dict[str, Any]:
    require_dashboard(request)
    rule = await request.json()
    if not isinstance(rule, dict):
        raise HTTPException(status_code=422, detail="La regla debe ser un objeto JSON")
    with db() as connection:
        if rules_store.get_rule(connection, rule_id) is None:
            raise HTTPException(status_code=404, detail="Regla no encontrada")
    return await run_in_threadpool(_save, {**rule, "id": rule_id}, DASHBOARD_USER)


@app.delete("/api/rules/{rule_id}")
def api_delete_rule(rule_id: str, request: Request) -> dict[str, Any]:
    require_dashboard(request)
    with DB_LOCK, db() as connection:
        revision = rules_store.delete_rule(connection, rule_id, DASHBOARD_USER)
    if revision is None:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    return {"deleted": rule_id, "revision": revision, **push_to_guard(revision)}


@app.get("/api/rules/{rule_id}/history")
def api_rule_history(rule_id: str, request: Request) -> dict[str, Any]:
    require_dashboard(request)
    with db() as connection:
        return {"rule_id": rule_id, "history": rules_store.rule_history(connection, rule_id)}


@app.post("/api/rules/{rule_id}/rollback")
async def api_rollback_rule(rule_id: str, request: Request) -> dict[str, Any]:
    require_dashboard(request)
    payload = await request.json()
    with db() as connection:
        snapshot = rules_store.rollback_snapshot(connection, rule_id, int(payload.get("version", 0)))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Versión no encontrada")
    return await run_in_threadpool(_save, snapshot, DASHBOARD_USER)


@app.post("/api/rules/test")
async def api_test_rule(request: Request) -> dict[str, Any]:
    """Prueba un texto contra las reglas activas, o contra una regla en borrador antes de guardarla."""
    require_dashboard(request)
    payload = await request.json()
    body: dict[str, Any] = {"text": str(payload.get("text") or "")}
    if isinstance(payload.get("rule"), dict):
        body["rule"] = payload["rule"]
    try:
        return await run_in_threadpool(guard_request, "/admin/test", body)
    except GuardUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"policy-guard no responde ({exc})")


# --- Analítica de uso ---------------------------------------------------------------------


@app.get("/usage")
def usage_page(request: Request) -> FileResponse:
    require_dashboard(request)
    return FileResponse(STATIC_DIR / "usage.html", headers=NO_STORE)


def _taxonomy() -> dict[str, Any]:
    return {
        "tasks": analytics.TASK_CATEGORIES,
        "occupations": analytics.OCCUPATION_GROUPS,
        "patterns": {key: {"mode": value[0], "description": value[1]} for key, value in analytics.PATTERNS.items()},
    }


@app.get("/api/analytics/status")
def analytics_status(request: Request) -> dict[str, Any]:
    require_dashboard(request)
    with db() as connection:
        counts = {
            row["status"]: row["n"]
            for row in connection.execute("SELECT status, COUNT(*) n FROM event_analysis GROUP BY status").fetchall()
        }
        pending = connection.execute(
            "SELECT COUNT(*) FROM audit_events e LEFT JOIN event_analysis a ON a.audit_id=e.audit_id WHERE e.prompt_chars>0 AND a.audit_id IS NULL"
        ).fetchone()[0]
    return {
        "enabled": ANALYTICS_ENABLED,
        "model": ANALYTICS_MODEL,
        "ollama_url": OLLAMA_URL,
        "ollama": analytics.ollama_status(OLLAMA_URL, ANALYTICS_MODEL),
        "worker": ANALYTICS_STATE,
        "done": counts.get("done", 0),
        "failed": counts.get("error", 0),
        "pending": pending,
        "taxonomy": _taxonomy(),
    }


@app.get("/api/analytics/summary")
def analytics_summary(request: Request, hours: int = Query(168, ge=1, le=8760)) -> dict[str, Any]:
    require_dashboard(request)
    with db() as connection:
        return analytics.summary(connection, hours)


@app.get("/api/analytics/explorer")
def analytics_explorer(request: Request, occupation: str, hours: int = Query(168, ge=1, le=8760)) -> dict[str, Any]:
    require_dashboard(request)
    with db() as connection:
        return analytics.explorer(connection, hours, occupation)


@app.post("/api/analytics/reanalyze")
async def analytics_reanalyze(request: Request) -> dict[str, Any]:
    """Vuelve a clasificar: solo los fallidos, o todo (por ejemplo tras cambiar de modelo)."""
    require_dashboard(request)
    payload = await request.json()
    scope = payload.get("scope", "errors") if isinstance(payload, dict) else "errors"
    if scope not in {"errors", "all"}:
        raise HTTPException(status_code=422, detail="scope debe ser 'errors' o 'all'")
    with DB_LOCK, db() as connection:
        query = "DELETE FROM event_analysis" + (" WHERE status='error'" if scope == "errors" else "")
        cleared = connection.execute(query).rowcount
    return {"status": "ok", "queued": cleared}
