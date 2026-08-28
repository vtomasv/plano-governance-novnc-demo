#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


EXPECTED: dict[str, set[tuple[int, int]]] = {
    "control-center": {(10000, env_int("CONTROL_CENTER_PORT", 10000))},
    "desktop-chatgpt": {(6080, env_int("CHATGPT_NOVNC_PORT", 6080))},
    "desktop-claude": {(6080, env_int("CLAUDE_NOVNC_PORT", 6081))},
    "desktop-grok": {(6080, env_int("GROK_NOVNC_PORT", 6082))},
    "plano": {
        (12000, env_int("PLANO_PORT", 12000)),
        (8001, env_int("PLANO_AGENT_PORT", 8001)),
        (9901, env_int("PLANO_ADMIN_PORT", 19901)),
    },
    "policy-guard": {(10500, env_int("POLICY_GUARD_PORT", 10500))},
    "provider-sim": {(10501, env_int("PROVIDER_SIM_PORT", 10501))},
    "provider-web-sim": {(8443, env_int("PROVIDER_TLS_PORT", 18443))},
    "governed-agent": {(10600, env_int("GOVERNED_AGENT_PORT", 10600))},
    "jaeger": {
        (16686, env_int("JAEGER_UI_PORT", 16686)),
        (4317, env_int("OTLP_GRPC_PORT", 4317)),
        (4318, env_int("OTLP_HTTP_PORT", 4318)),
    },
    "proxy-interceptor": {(8081, env_int("MITMPROXY_UI_PORT", 8081))},
}


def main() -> int:
    if len(sys.argv) > 1:
        config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        config = json.loads(result.stdout)
    services = config.get("services", {})
    failures: list[str] = []

    for service, expected in EXPECTED.items():
        definition = services.get(service)
        if definition is None:
            failures.append(f"falta el servicio {service}")
            continue
        if definition.get("network_mode") == "host":
            failures.append(f"{service} usa network_mode=host en el Compose principal")
        actual = {
            (int(port["target"]), int(port["published"]))
            for port in definition.get("ports", [])
            if port.get("protocol", "tcp") == "tcp"
        }
        missing = expected - actual
        if missing:
            failures.append(f"{service} no publica {sorted(missing)}; actual={sorted(actual)}")

    if failures:
        print("Validación de puertos: ERROR", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Validación de puertos: OK")
    for service, expected in EXPECTED.items():
        mappings = ", ".join(f"{published}->{target}" for target, published in sorted(expected))
        print(f"- {service}: {mappings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
