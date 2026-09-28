"""Reglas de fábrica. Se usan como respaldo y para sembrar el dashboard la primera vez."""

from __future__ import annotations

from typing import Any

POLICY_MESSAGE = "No es posible realizar preguntas sobre el presidente de Argentina."
DATA_LOSS_MESSAGE = "La solicitud fue bloqueada para prevenir una posible fuga de datos sensibles."

_PRESIDENT = {
    "label": "Presidente",
    "terms": [
        "presidente", "presidenta", "presidencia", "presidential", "president",
        "mandatario", "mandataria", "jefe de estado", "head of state",
    ],
}

_SECRETS: list[tuple[str, str, str, bool]] = [
    ("private_key", "Clave privada", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", False),
    ("openai_key", "API key de OpenAI", r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b", True),
    ("anthropic_key", "API key de Anthropic", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b", False),
    ("aws_access_key", "Access key de AWS", r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", True),
    ("github_token", "Token de GitHub", r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b", True),
    ("bearer_token", "Bearer token", r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}\b", False),
    (
        "assigned_secret",
        "Secreto asignado (password, api_key, token)",
        r"\b(?:password|passwd|api[_ -]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}",
        False,
    ),
]


def default_rules() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {
            "id": "argentina_president",
            "name": "Presidente de Argentina",
            "description": "Bloquea preguntas sobre el presidente de Argentina, incluidas variantes de Milei con errores de tipeo.",
            "enabled": True,
            "mode": "enforce",
            "priority": 10,
            "message": POLICY_MESSAGE,
            "clauses": [
                [_PRESIDENT, {"label": "Argentina", "terms": ["argentina", "argentino", "argentina's", "casa rosada"]}],
                [_PRESIDENT, {"label": "Milei y variantes", "fuzzy_terms": ["milei", "miley", "mliey"]}],
            ],
        }
    ]
    for index, (rule_id, name, pattern, case_sensitive) in enumerate(_SECRETS):
        rules.append(
            {
                "id": rule_id,
                "name": name,
                "description": "Prevención de fuga de datos: bloquea credenciales pegadas en el prompt.",
                "enabled": True,
                "mode": "enforce",
                "priority": 100 + index * 10,
                "message": DATA_LOSS_MESSAGE,
                "clauses": [[{"label": "Patrón", "regex": [pattern], "case_sensitive": case_sensitive}]],
            }
        )
    return rules
