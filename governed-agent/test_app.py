import json

import app


def test_nested_filter_chain_error_is_human_readable():
    nested = {
        "error": {
            "type": "policy_violation",
            "code": "argentina_president",
            "message": "No es posible realizar preguntas sobre el presidente de Argentina.",
            "decision_id": "decision-123",
            "audit_id": "audit-123",
        }
    }
    value = {"error": "FilterChainError", "agent_response": json.dumps(nested)}
    message, rule, decision_id = app.error_detail(value)
    audit_id, parsed_decision_id = app.policy_identifiers(value)
    assert message == "No es posible realizar preguntas sobre el presidente de Argentina."
    assert rule == "argentina_president"
    assert decision_id == "decision-123"
    assert audit_id == "audit-123"
    assert parsed_decision_id == "decision-123"


def test_gemini_routes_to_local_model():
    assert app.choose_model("gemini") == "custom/local-gemini"


def test_agent_redacts_api_key_before_egress():
    redacted, count = app.redact_text("clave sk-proj-abcdefghijklmnopqrstuvwxyz123456")
    assert count == 1
    assert "sk-proj" not in redacted
    assert "[REDACTED_BY_AGENT]" in redacted
