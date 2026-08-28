#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Uso: validate_mac_publisher.py <compose-config.json>")

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
services = config.get("services", {})
errors: list[str] = []


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


expected = {
    (10000, env_int("CONTROL_CENTER_PORT", 10000)),
    (6080, env_int("CHATGPT_NOVNC_PORT", 6080)),
    (6081, env_int("CLAUDE_NOVNC_PORT", 6081)),
    (6082, env_int("GROK_NOVNC_PORT", 6082)),
    (12000, env_int("PLANO_PORT", 12000)),
    (8001, env_int("PLANO_AGENT_PORT", 8001)),
    (19901, env_int("PLANO_ADMIN_PORT", 19901)),
    (10500, env_int("POLICY_GUARD_PORT", 10500)),
    (10501, env_int("PROVIDER_SIM_PORT", 10501)),
    (18443, env_int("PROVIDER_TLS_PORT", 18443)),
    (10600, env_int("GOVERNED_AGENT_PORT", 10600)),
    (16686, env_int("JAEGER_UI_PORT", 16686)),
    (4317, env_int("OTLP_GRPC_PORT", 4317)),
    (4318, env_int("OTLP_HTTP_PORT", 4318)),
    (8081, env_int("MITMPROXY_UI_PORT", 8081)),
    (8404, env_int("HOST_PUBLISHER_STATS_PORT", 8404)),
}

publisher = services.get("host-publisher")
if not publisher:
    errors.append("falta host-publisher")
else:
    actual = {
        (int(item["target"]), int(item["published"]))
        for item in publisher.get("ports", [])
        if item.get("protocol", "tcp") == "tcp"
    }
    missing = expected - actual
    extra = actual - expected
    if missing:
        errors.append(f"host-publisher no publica {sorted(missing)}")
    if extra:
        errors.append(f"host-publisher tiene bindings inesperados {sorted(extra)}")
    for item in publisher.get("ports", []):
        if item.get("host_ip") != "127.0.0.1":
            errors.append(f"binding no limitado a loopback: {item}")

    networks = set(publisher.get("networks", {}))
    required_networks = {"control", "upstream-sim", "publish"}
    if not required_networks.issubset(networks):
        errors.append(f"host-publisher sin redes requeridas: {sorted(required_networks - networks)}")
    if "egress" in networks:
        errors.append("host-publisher no debe estar conectado a egress")

internal_services = {
    "control-center",
    "policy-guard",
    "provider-sim",
    "provider-web-sim",
    "jaeger",
    "plano",
    "governed-agent",
    "proxy-interceptor",
    "desktop-chatgpt",
    "desktop-claude",
    "desktop-grok",
}
for name in sorted(internal_services):
    if services.get(name, {}).get("ports"):
        errors.append(f"{name} conserva publicación directa")

for name in ("desktop-chatgpt", "desktop-claude", "desktop-grok"):
    networks = set(services.get(name, {}).get("networks", {}))
    if networks != {"control"}:
        errors.append(f"{name} debe estar solo en control; actual={sorted(networks)}")

for name, service in services.items():
    networks = set(service.get("networks", {}))
    if "egress" in networks and name not in {"plano", "proxy-interceptor"}:
        errors.append(f"{name} tiene egress no autorizado")

if errors:
    print("Validación del publisher Mac: ERROR", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Validación del publisher Mac: OK")
print(f"- host-publisher: {len(expected)} bindings en 127.0.0.1")
print(f"- servicios sin bindings directos: {len(internal_services)}")
print("- escritorios: solo red control")
print("- egress: únicamente plano y proxy-interceptor")
