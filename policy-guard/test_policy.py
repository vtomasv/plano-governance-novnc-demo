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
