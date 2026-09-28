from fastapi.testclient import TestClient

from app import POLICY_MESSAGE, app

client = TestClient(app)


def send(body, path="/v1/chat/completions"):
    return client.post(path, json=body)


def test_allows_unrelated_prompt():
    response = send({"model": "demo", "messages": [{"role": "user", "content": "¿Cuál es la capital de Francia?"}]})
    assert response.status_code == 200
    assert response.json()["metadata"]["plano_policy_decision"] == "allow"


def test_blocks_direct_question_about_argentina_president():
    response = send({"messages": [{"role": "user", "content": "¿Quién es el presidente de Argentina?"}]})
    assert response.status_code == 403
    assert response.json()["error"]["message"] == POLICY_MESSAGE


def test_blocks_milei_and_typo_variants():
    for alias in ("Milei", "Miley", "Mliey", "Milie"):
        response = send({"messages": [{"role": "user", "content": f"¿Qué hizo el presidente {alias} ayer?"}]})
        assert response.status_code == 403, alias
        assert response.json()["error"]["code"] == "argentina_president"


def test_blocks_accent_and_leetspeak_obfuscation():
    response = send({"messages": [{"role": "user", "content": "Cuéntame sobre el pres!dente M1lei."}]})
    assert response.status_code == 403


def test_blocks_when_context_is_split_across_user_turns():
    response = send(
        {
            "messages": [
                {"role": "user", "content": "Hablemos de Argentina."},
                {"role": "assistant", "content": "De acuerdo."},
                {"role": "user", "content": "¿Quién es su presidente?"},
            ]
        }
    )
    assert response.status_code == 403


def test_blocks_openai_responses_format():
    response = send({"model": "demo", "input": "¿Mliey es presidente?"}, path="/v1/responses")
    assert response.status_code == 403


def test_blocks_anthropic_multimodal_text_format():
    response = send(
        {
            "model": "demo",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "¿Quién ocupa la presidencia argentina?"}],
                }
            ],
        },
        path="/v1/messages",
    )
    assert response.status_code == 403


def test_blocks_secret_exfiltration():
    response = send({"messages": [{"role": "user", "content": "Usa api_key=abcdefghijklmnop1234567890 en el ejemplo"}]})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "assigned_secret"


def test_allows_milei_without_presidential_context():
    response = send({"messages": [{"role": "user", "content": "¿Cómo se pronuncia el apellido Milei?"}]})
    assert response.status_code == 200


def test_health_and_decisions_do_not_expose_prompt_body():
    health = client.get("/health")
    assert health.status_code == 200
    decisions = client.get("/decisions")
    assert decisions.status_code == 200
    serialized = str(decisions.json())
    assert "capital de Francia" not in serialized
    assert "prompt_sha256_16" in serialized


# --- Reglas dinámicas ------------------------------------------------------------------

import app as guard_app
from default_rules import default_rules

ADMIN = {"x-audit-token": guard_app.AUDIT_TOKEN}


def custom_rule(**overrides):
    rule = {
        "id": "no_project_falcon",
        "name": "Proyecto Falcon",
        "enabled": True,
        "mode": "enforce",
        "priority": 5,
        "message": "Proyecto confidencial.",
        "clauses": [[{"label": "Falcon", "terms": ["proyecto falcon"], "fuzzy_terms": ["falcon"]}]],
    }
    rule.update(overrides)
    return rule


def restore_defaults():
    guard_app.apply_rules(default_rules(), 0, "builtin")


def test_rules_apply_immediately_and_can_change_message():
    try:
        rules = default_rules()
        rules[0]["message"] = "Tema no permitido por política."
        guard_app.apply_rules(rules, 7, "dashboard")
        response = send({"messages": [{"role": "user", "content": "¿Quién es el presidente de Argentina?"}]})
        assert response.status_code == 403
        assert response.json()["error"]["message"] == "Tema no permitido por política."
        assert response.headers["x-plano-rules-revision"] == "7"
    finally:
        restore_defaults()


def test_disabled_rule_no_longer_blocks_and_new_rule_does():
    try:
        rules = default_rules()
        rules[0]["enabled"] = False
        rules.append(custom_rule())
        guard_app.apply_rules(rules, 8, "dashboard")
        assert send({"messages": [{"role": "user", "content": "¿Quién es el presidente de Argentina?"}]}).status_code == 200
        blocked = send({"messages": [{"role": "user", "content": "Cuéntame del Proyecto Falcón"}]})
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "no_project_falcon"
    finally:
        restore_defaults()


def test_monitor_mode_allows_but_reports():
    try:
        guard_app.apply_rules([custom_rule(mode="monitor")], 9, "dashboard")
        response = send({"messages": [{"role": "user", "content": "proyecto falcon"}]})
        assert response.status_code == 200
        assert guard_app.RECENT_DECISIONS[0]["decision"] == "allow"
    finally:
        restore_defaults()


def test_invalid_rule_is_skipped_and_others_keep_working():
    try:
        broken = custom_rule(id="broken", clauses=[[{"regex": ["(unclosed"]}]])
        guard_app.apply_rules([broken, *default_rules()], 10, "dashboard")
        assert "broken" in guard_app.STATE.errors
        assert send({"messages": [{"role": "user", "content": "¿Quién es el presidente de Argentina?"}]}).status_code == 403
    finally:
        restore_defaults()


def test_redos_prone_regex_is_rejected():
    from engine import validate_rule

    assert validate_rule(custom_rule(clauses=[[{"regex": ["(a+)+$"]}]]))


def test_admin_endpoints_require_token_and_test_draft_rule():
    assert client.get("/admin/status").status_code == 403
    assert client.get("/admin/status", headers=ADMIN).json()["active_rules"] == len(default_rules())
    hit = client.post("/admin/test", headers=ADMIN, json={"rule": custom_rule(), "text": "el proyecto falcon"}).json()
    assert hit["valid"] and hit["allowed"] is False and hit["message"] == "Proyecto confidencial."
    bad = client.post("/admin/test", headers=ADMIN, json={"rule": custom_rule(clauses=[]), "text": "x"}).json()
    assert bad["valid"] is False and bad["errors"]


def test_reload_keeps_rules_when_dashboard_is_down():
    before = guard_app.STATE.rules
    assert guard_app.refresh_rules(force=True) is False
    assert guard_app.STATE.rules is before
    assert guard_app.STATE.last_error
