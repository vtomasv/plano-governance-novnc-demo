"""Motor de reglas declarativas del policy-guard.

Una regla es un JSON editable desde el dashboard. Se dispara si CUALQUIERA de sus
`clauses` se cumple (OR) y una cláusula se cumple si TODOS sus grupos coinciden (AND).
Un grupo coincide si CUALQUIERA de sus `terms`, `fuzzy_terms` o `regex` aparece en el texto.

    {"id": "...", "name": "...", "enabled": true, "mode": "enforce|monitor",
     "priority": 10, "message": "...",
     "clauses": [[{"label": "...", "terms": [], "fuzzy_terms": [], "regex": [],
                   "case_sensitive": false}]]}
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_RULES = 200
MAX_CLAUSES = 20
MAX_GROUPS = 10
MAX_ITEMS = 200
MAX_ITEM_CHARS = 300
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]")


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


def validate_rule(rule: Any) -> list[str]:
    """Devuelve la lista de errores estructurales; vacía si la regla es válida."""
    errors: list[str] = []
    if not isinstance(rule, dict):
        return ["La regla debe ser un objeto JSON."]
    rule_id = rule.get("id")
    if not isinstance(rule_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", rule_id):
        errors.append("id: use 2-63 caracteres en minúsculas, dígitos, '_' o '-'.")
    if not str(rule.get("name") or "").strip():
        errors.append("name: es obligatorio.")
    if rule.get("mode", "enforce") not in {"enforce", "monitor"}:
        errors.append("mode: debe ser 'enforce' o 'monitor'.")
    if not isinstance(rule.get("priority", 100), int) or isinstance(rule.get("priority"), bool):
        errors.append("priority: debe ser un entero.")
    if not str(rule.get("message") or "").strip() or len(str(rule["message"])) > 500:
        errors.append("message: obligatorio, máximo 500 caracteres.")
    clauses = rule.get("clauses")
    if not isinstance(clauses, list) or not clauses or len(clauses) > MAX_CLAUSES:
        errors.append(f"clauses: entre 1 y {MAX_CLAUSES} cláusulas.")
        return errors
    for ci, clause in enumerate(clauses, 1):
        if not isinstance(clause, list) or not clause or len(clause) > MAX_GROUPS:
            errors.append(f"cláusula {ci}: entre 1 y {MAX_GROUPS} grupos.")
            continue
        for gi, group in enumerate(clause, 1):
            where = f"cláusula {ci}, grupo {gi}"
            if not isinstance(group, dict):
                errors.append(f"{where}: debe ser un objeto.")
                continue
            total = 0
            for key in ("terms", "fuzzy_terms", "regex"):
                items = group.get(key, [])
                if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
                    errors.append(f"{where}: '{key}' debe ser una lista de textos no vacíos.")
                    continue
                total += len(items)
                if len(items) > MAX_ITEMS or any(len(i) > MAX_ITEM_CHARS for i in items):
                    errors.append(f"{where}: '{key}' excede {MAX_ITEMS} elementos o {MAX_ITEM_CHARS} caracteres.")
                    continue
                if key == "regex":
                    for pattern in items:
                        try:
                            re.compile(pattern)
                        except re.error as exc:
                            errors.append(f"{where}: regex inválida '{pattern[:40]}': {exc}")
                        else:
                            if _NESTED_QUANTIFIER.search(pattern):
                                errors.append(f"{where}: regex '{pattern[:40]}' tiene cuantificadores anidados (riesgo de ReDoS).")
                elif key == "fuzzy_terms" and any(len(normalize_text(i).replace(" ", "")) < 4 for i in items):
                    errors.append(f"{where}: 'fuzzy_terms' exige palabras de al menos 4 letras.")
            if total == 0:
                errors.append(f"{where}: necesita al menos un término, término difuso o regex.")
    return errors


@dataclass(frozen=True)
class _Group:
    terms: tuple[str, ...]
    fuzzy: tuple[str, ...]
    regexes: tuple[re.Pattern[str], ...]

    def matches(self, normalized: str, compact: str, words: tuple[str, ...], raw: str) -> bool:
        if any(term in normalized for term in self.terms):
            return True
        for target in self.fuzzy:
            if target in compact:
                return True
            if any(
                len(target) - 1 <= len(word) <= len(target) + 1 and damerau_levenshtein_at_most_one(word, target)
                for word in words
            ):
                return True
        return any(pattern.search(raw) for pattern in self.regexes)


@dataclass(frozen=True)
class CompiledRule:
    id: str
    name: str
    mode: str
    priority: int
    message: str
    clauses: tuple[tuple[_Group, ...], ...]

    def matches(self, raw: str, normalized: str) -> bool:
        compact = normalized.replace(" ", "")
        words = tuple(re.findall(r"[a-z0-9]+", normalized))
        return any(all(g.matches(normalized, compact, words, raw) for g in clause) for clause in self.clauses)


def compile_rule(rule: dict[str, Any]) -> CompiledRule:
    errors = validate_rule(rule)
    if errors:
        raise ValueError("; ".join(errors))
    clauses = []
    for clause in rule["clauses"]:
        groups = []
        for group in clause:
            flags = 0 if group.get("case_sensitive") else re.IGNORECASE
            groups.append(
                _Group(
                    terms=tuple(t for t in (normalize_text(x) for x in group.get("terms", [])) if t),
                    fuzzy=tuple(t for t in (normalize_text(x).replace(" ", "") for x in group.get("fuzzy_terms", [])) if t),
                    regexes=tuple(re.compile(p, flags) for p in group.get("regex", [])),
                )
            )
        clauses.append(tuple(groups))
    return CompiledRule(
        id=rule["id"],
        name=str(rule["name"]),
        mode=rule.get("mode", "enforce"),
        priority=int(rule.get("priority", 100)),
        message=str(rule["message"]),
        clauses=tuple(clauses),
    )


def compile_rules(rules: list[dict[str, Any]]) -> tuple[tuple[CompiledRule, ...], dict[str, str]]:
    """Compila las reglas habilitadas. Las inválidas se omiten y se informan en `errors`."""
    compiled: list[CompiledRule] = []
    errors: dict[str, str] = {}
    for rule in rules[:MAX_RULES]:
        if isinstance(rule, dict) and rule.get("enabled", True) is False:
            continue
        try:
            compiled.append(compile_rule(rule))
        except ValueError as exc:
            errors[str(rule.get("id") if isinstance(rule, dict) else "?")] = str(exc)
    compiled.sort(key=lambda item: (item.priority, item.id))
    return tuple(compiled), errors


def evaluate(rules: tuple[CompiledRule, ...], texts: list[str]) -> tuple[CompiledRule | None, list[str]]:
    """Devuelve la primera regla `enforce` que coincide y los ids de reglas `monitor` que coinciden."""
    raw = "\n".join(texts)
    normalized = normalize_text(raw)
    blocking: CompiledRule | None = None
    monitored: list[str] = []
    for rule in rules:
        if rule.mode == "enforce" and blocking is not None:
            continue
        if not rule.matches(raw, normalized):
            continue
        if rule.mode == "monitor":
            monitored.append(rule.id)
        else:
            blocking = rule
    return blocking, monitored
