"""Persistencia de reglas de política con historial versionado.

Cada cambio incrementa `revision` (global) y `version` (por regla) y guarda una foto
en `rule_history`, lo que permite auditar quién cambió qué y volver atrás.
La validación semántica la hace el policy-guard, que es quien las ejecuta.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    mode TEXT NOT NULL DEFAULT 'enforce',
    priority INTEGER NOT NULL DEFAULT 100,
    message TEXT NOT NULL,
    clauses_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT 'system'
);
CREATE TABLE IF NOT EXISTS policy_rule_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    action TEXT NOT NULL,
    snapshot_json TEXT,
    changed_at TEXT NOT NULL,
    changed_by TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_history ON policy_rule_history(rule_id, seq DESC);
CREATE TABLE IF NOT EXISTS policy_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _meta_get(connection: sqlite3.Connection, key: str, default: str = "0") -> str:
    row = connection.execute("SELECT value FROM policy_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _meta_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO policy_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def revision(connection: sqlite3.Connection) -> int:
    return int(_meta_get(connection, "revision"))


def needs_seed(connection: sqlite3.Connection) -> bool:
    return _meta_get(connection, "seeded", "0") != "1"


def _bump(connection: sqlite3.Connection) -> int:
    value = revision(connection) + 1
    _meta_set(connection, "revision", str(value))
    return value


def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "enabled": bool(row["enabled"]),
        "mode": row["mode"],
        "priority": row["priority"],
        "message": row["message"],
        "clauses": json.loads(row["clauses_json"]),
        "version": row["version"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def list_rules(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM policy_rules ORDER BY priority, id").fetchall()
    return [_to_dict(row) for row in rows]


def get_rule(connection: sqlite3.Connection, rule_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM policy_rules WHERE id=?", (rule_id,)).fetchone()
    return _to_dict(row) if row else None


def _history(connection: sqlite3.Connection, rule_id: str, version: int, action: str, snapshot: dict | None, actor: str) -> None:
    connection.execute(
        "INSERT INTO policy_rule_history(rule_id,version,action,snapshot_json,changed_at,changed_by) VALUES(?,?,?,?,?,?)",
        (rule_id, version, action, json.dumps(snapshot, ensure_ascii=False) if snapshot else None, _now(), actor),
    )


def save_rule(connection: sqlite3.Connection, rule: dict[str, Any], actor: str, action: str | None = None) -> tuple[dict[str, Any], int]:
    """Crea o actualiza una regla. Devuelve (regla guardada, nueva revisión global)."""
    current = get_rule(connection, rule["id"])
    version = (current["version"] + 1) if current else 1
    now = _now()
    values = (
        rule["id"], str(rule["name"]).strip(), str(rule.get("description") or "").strip(),
        1 if rule.get("enabled", True) else 0, rule.get("mode", "enforce"), int(rule.get("priority", 100)),
        str(rule["message"]).strip(), json.dumps(rule["clauses"], ensure_ascii=False), version, now, actor,
    )
    connection.execute(
        """INSERT INTO policy_rules(id,name,description,enabled,mode,priority,message,clauses_json,version,updated_at,updated_by)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, enabled=excluded.enabled,
             mode=excluded.mode, priority=excluded.priority, message=excluded.message, clauses_json=excluded.clauses_json,
             version=excluded.version, updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        values,
    )
    saved = get_rule(connection, rule["id"])
    assert saved is not None
    _history(connection, saved["id"], version, action or ("update" if current else "create"), saved, actor)
    return saved, _bump(connection)


def delete_rule(connection: sqlite3.Connection, rule_id: str, actor: str) -> int | None:
    current = get_rule(connection, rule_id)
    if current is None:
        return None
    connection.execute("DELETE FROM policy_rules WHERE id=?", (rule_id,))
    _history(connection, rule_id, current["version"] + 1, "delete", current, actor)
    return _bump(connection)


def rule_history(connection: sqlite3.Connection, rule_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM policy_rule_history WHERE rule_id=? ORDER BY seq DESC LIMIT ?", (rule_id, limit)
    ).fetchall()
    return [
        {
            "version": row["version"], "action": row["action"], "changed_at": row["changed_at"],
            "changed_by": row["changed_by"], "snapshot": json.loads(row["snapshot_json"]) if row["snapshot_json"] else None,
        }
        for row in rows
    ]


def rollback_snapshot(connection: sqlite3.Connection, rule_id: str, version: int) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT snapshot_json FROM policy_rule_history WHERE rule_id=? AND version=? AND snapshot_json IS NOT NULL ORDER BY seq DESC LIMIT 1",
        (rule_id, version),
    ).fetchone()
    return json.loads(row[0]) if row else None


def seed(connection: sqlite3.Connection, rules: list[dict[str, Any]]) -> int:
    """Siembra las reglas de fábrica una sola vez; borrar todas las reglas no las restaura."""
    if not needs_seed(connection):
        return revision(connection)
    for rule in rules:
        if get_rule(connection, rule["id"]) is None:
            save_rule(connection, rule, "system", action="seed")
    _meta_set(connection, "seeded", "1")
    return _bump(connection)
