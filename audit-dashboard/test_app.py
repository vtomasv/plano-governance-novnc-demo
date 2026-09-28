from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

import app as audit


def configure_tmp_db(tmp_path):
    audit.DATA_DIR = tmp_path
    audit.DB_PATH = tmp_path / "audit.db"
    audit.init_db()


def test_correlated_upsert_preserves_prompt(tmp_path):
    configure_tmp_db(tmp_path)
    first = audit.upsert_event({
        "audit_id": "evt-1",
        "prompt_text": "Explica la fotosíntesis",
        "provider": "chatgpt",
        "decision": "allow",
        "filtered": False,
        "state": "pending",
    })
    assert first["topic"] == "ciencia_y_educacion"
    assert first["prompt_text"] == "Explica la fotosíntesis"

    completed = audit.upsert_event({
        "audit_id": "evt-1",
        "response_text": "La fotosíntesis convierte luz en energía química.",
        "state": "completed",
        "status_code": 200,
    })
    assert completed["prompt_text"] == "Explica la fotosíntesis"
    assert completed["response_text"].startswith("La fotosíntesis")
    assert completed["completed_at"]


def test_denied_event_and_secret_redaction(tmp_path):
    configure_tmp_db(tmp_path)
    item = audit.upsert_event({
        "audit_id": "evt-deny",
        "prompt_text": "Usa api_key=abcdefghijklmnop1234567890",
        "decision": "deny",
        "rule": "api_key_assignment",
        "policy_message": "posible fuga",
    })
    assert item["filtered"] is True
    assert item["state"] == "blocked"
    assert "abcdefghijklmnop1234567890" not in item["prompt_text"]
    assert "REDACTED_BY_AUDIT" in item["prompt_text"]
    assert item["redaction_count"] >= 1


def test_dashboard_auth_and_ingest(tmp_path, monkeypatch):
    configure_tmp_db(tmp_path)
    monkeypatch.setattr(audit, "INGEST_TOKEN", "ingest-test")
    monkeypatch.setattr(audit, "DASHBOARD_USER", "admin")
    monkeypatch.setattr(audit, "DASHBOARD_PASSWORD", "secret-test")
    client = TestClient(audit.app)

    denied = client.post("/ingest", json={"prompt_text": "hola"})
    assert denied.status_code == 403
    accepted = client.post(
        "/ingest",
        headers={"x-audit-token": "ingest-test"},
        json={"audit_id": "evt-api", "prompt_text": "Escribe código Python", "decision": "allow"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["topic"] == "programacion"

    assert client.get("/api/events").status_code == 401
    basic = base64.b64encode(b"admin:secret-test").decode()
    listed = client.get("/api/events", headers={"authorization": f"Basic {basic}"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_properties_drop_sensitive_keys():
    cleaned = audit.clean_properties({
        "browser": "Chromium",
        "authorization": "Bearer secret",
        "cookie": "session=secret",
        "temperature": 0.2,
    })
    assert cleaned == {"browser": "Chromium", "temperature": 0.2}


# --- Gestión de reglas ------------------------------------------------------------------

import pytest

RULE = {
    "id": "no_falcon",
    "name": "Proyecto Falcon",
    "message": "Proyecto confidencial.",
    "clauses": [[{"terms": ["proyecto falcon"]}]],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    configure_tmp_db(tmp_path)
    calls = []

    def fake_guard(path, payload=None, method="POST", timeout=5.0):
        calls.append(path)
        if path == "/admin/test":
            return {"valid": bool(payload["rule"].get("clauses")), "errors": ["clauses vacías"]}
        if path == "/admin/reload":
            with audit.db() as connection:
                return {"revision": audit.rules_store.revision(connection)}
        return {"revision": 0}

    monkeypatch.setattr(audit, "guard_request", fake_guard)
    test_client = TestClient(audit.app)
    token = base64.b64encode(f"{audit.DASHBOARD_USER}:{audit.DASHBOARD_PASSWORD}".encode()).decode()
    test_client.headers.update({"authorization": f"Basic {token}"})
    test_client.calls = calls
    return test_client


INGEST = {"x-audit-token": audit.INGEST_TOKEN}


def test_seed_only_once_and_guard_sync(client):
    assert client.get("/policy/rules").status_code == 403
    first = client.get("/policy/rules", headers=INGEST).json()
    assert first["needs_seed"] and first["rules"] == []
    client.post("/policy/seed", headers=INGEST, json={"rules": [{**RULE, "id": "seeded"}]})
    after = client.get("/policy/rules", headers=INGEST).json()
    assert not after["needs_seed"] and [r["id"] for r in after["rules"]] == ["seeded"]
    client.delete("/api/rules/seeded")
    client.post("/policy/seed", headers=INGEST, json={"rules": [{**RULE, "id": "seeded"}]})
    assert client.get("/policy/rules", headers=INGEST).json()["rules"] == []


def test_create_update_applies_to_guard_and_versions(client):
    created = client.post("/api/rules", json=RULE).json()
    assert created["applied"] and created["rule"]["version"] == 1
    assert client.post("/api/rules", json=RULE).status_code == 409
    updated = client.put("/api/rules/no_falcon", json={**RULE, "message": "Nuevo mensaje"}).json()
    assert updated["applied"] and updated["rule"]["version"] == 2 and updated["revision"] > created["revision"]
    assert "/admin/reload" in client.calls
    history = client.get("/api/rules/no_falcon/history").json()["history"]
    assert [h["version"] for h in history] == [2, 1]


def test_rollback_restores_previous_version(client):
    client.post("/api/rules", json=RULE)
    client.put("/api/rules/no_falcon", json={**RULE, "message": "Cambiado"})
    restored = client.post("/api/rules/no_falcon/rollback", json={"version": 1}).json()
    assert restored["rule"]["message"] == "Proyecto confidencial." and restored["rule"]["version"] == 3


def test_invalid_rule_rejected_and_not_saved(client):
    response = client.post("/api/rules", json={**RULE, "clauses": []})
    assert response.status_code == 422
    assert client.get("/api/rules").json()["rules"] == []


def test_saved_even_if_guard_reload_fails(client, monkeypatch):
    def flaky(path, payload=None, method="POST", timeout=5.0):
        if path == "/admin/test":
            return {"valid": True}
        raise audit.GuardUnavailable("caído")

    monkeypatch.setattr(audit, "guard_request", flaky)
    result = client.post("/api/rules", json=RULE).json()
    assert result["applied"] is False and "sondeo" in result["warning"]
    assert client.get("/policy/rules", headers=INGEST).json()["rules"][0]["id"] == "no_falcon"


def test_rules_and_usage_require_authentication(tmp_path):
    configure_tmp_db(tmp_path)
    anonymous = TestClient(audit.app)
    for path in ("/api/rules", "/api/analytics/summary", "/rules", "/usage"):
        assert anonymous.get(path).status_code == 401


# --- Analítica de uso --------------------------------------------------------------------


def fake_classify(pattern, task="desarrollo_de_software", occupation="informatica_y_matematicas"):
    def run(base_url, model, prompt, timeout=120.0):
        if isinstance(pattern, dict):  # patrón según el texto del prompt
            chosen = next(value for key, value in pattern.items() if key in prompt)
        else:
            chosen = pattern
        return audit.analytics.parse_result(json.dumps({
            "task_category": task, "occupation_group": occupation, "usage_context": "trabajo",
            "interaction_pattern": chosen, "task_summary": "Escribir una función", "language": "es", "confidence": 0.9,
        }))
    return run


def test_parse_result_maps_pattern_to_mode_and_rejects_garbage():
    parsed = audit.analytics.parse_result('{"task_category":"x","occupation_group":"y","usage_context":"z","interaction_pattern":"aprendizaje","confidence":2}')
    assert parsed["mode"] == "aumentacion" and parsed["task_category"] == "otro" and parsed["confidence"] == 1.0
    with pytest.raises(ValueError):
        audit.analytics.parse_result('{"interaction_pattern":"inventado"}')
    with pytest.raises(ValueError):
        audit.analytics.parse_result("sin json")


def test_analysis_worker_classifies_and_summarizes(client, monkeypatch):
    for idx, pattern in enumerate(["directiva", "directiva", "aprendizaje", "iteracion"]):
        audit.upsert_event({"audit_id": f"a{idx}", "prompt_text": f"prompt {idx}", "decision": "allow", "state": "completed"})
    monkeypatch.setattr(audit.analytics, "classify", fake_classify({"prompt 0": "directiva", "prompt 1": "directiva", "prompt 2": "aprendizaje", "prompt 3": "iteracion"}))
    outcomes = [audit.analytics.analyze_one(audit.db, "http://x", "m") for _ in range(5)]
    assert outcomes == ["done"] * 4 + ["idle"]

    summary = client.get("/api/analytics/summary").json()
    assert summary["totals"]["count"] == 4 and summary["totals"]["automation"] == 2 and summary["totals"]["augmentation"] == 2 and summary["totals"]["automation_pct"] == 50.0
    assert summary["tasks"][0]["name"] == "desarrollo_de_software"

    explorer = client.get("/api/analytics/explorer", params={"occupation": "informatica_y_matematicas"}).json()
    assert explorer["tasks"][0]["examples"][0]["text"] == "Escribir una función"
    assert client.get("/api/events/a0").json()["analysis"]["interaction_pattern"] == "directiva"


def test_worker_reports_unavailable_without_marking_failure(client, monkeypatch):
    audit.upsert_event({"audit_id": "u1", "prompt_text": "hola", "state": "completed"})

    def down(*args, **kwargs):
        raise ConnectionRefusedError("sin ollama")

    monkeypatch.setattr(audit.analytics, "classify", down)
    assert audit.analytics.analyze_one(audit.db, "http://x", "m") == "unavailable"
    assert client.get("/api/analytics/summary").json()["totals"]["pending"] == 1


def test_bad_model_output_is_retried_then_given_up(client, monkeypatch):
    audit.upsert_event({"audit_id": "b1", "prompt_text": "hola", "state": "completed"})
    monkeypatch.setattr(audit.analytics, "classify", lambda *a, **k: audit.analytics.parse_result("basura"))
    results = [audit.analytics.analyze_one(audit.db, "http://x", "m") for _ in range(4)]
    assert results == ["error", "error", "error", "idle"]
    assert client.get("/api/analytics/summary").json()["totals"]["failed"] == 1
    assert client.post("/api/analytics/reanalyze", json={"scope": "errors"}).json()["queued"] == 1
