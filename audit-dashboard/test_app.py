from __future__ import annotations

import base64

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
