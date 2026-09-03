#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Uso: validate_mac_arm64.py <compose-config.json>")

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
services = config.get("services", {})
required = {
    "cert-init",
    "control-center",
    "audit-dashboard",
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
    "desktop-gemini",
    "host-publisher",
}

errors: list[str] = []
for name in sorted(required):
    service = services.get(name)
    if not service:
        errors.append(f"falta el servicio {name}")
        continue
    if service.get("platform") != "linux/arm64":
        errors.append(f"{name}: platform={service.get('platform')!r}; esperado 'linux/arm64'")

for name in ("provider-web-sim", "jaeger", "host-publisher"):
    image = services.get(name, {}).get("image", "")
    if "@sha256:" not in image:
        errors.append(f"{name}: la imagen externa no está fijada por digest arm64")

if errors:
    print("Validación macOS arm64: ERROR", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print("Validación macOS arm64: OK")
for name in sorted(required):
    print(f"- {name}: linux/arm64")
