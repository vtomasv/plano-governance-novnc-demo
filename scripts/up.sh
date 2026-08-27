#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Se creó .env desde .env.example"
fi

sudo docker compose up --build --detach --remove-orphans

for url in \
  "http://127.0.0.1:${PLANO_PORT:-12000}/v1/models" \
  "http://127.0.0.1:10600/health" \
  "http://127.0.0.1:${CHATGPT_NOVNC_PORT:-6080}/vnc.html" \
  "http://127.0.0.1:${CLAUDE_NOVNC_PORT:-6081}/vnc.html" \
  "http://127.0.0.1:${GROK_NOVNC_PORT:-6082}/vnc.html"; do
  ready=0
  for _ in $(seq 1 90); do
    if curl -fsS "$url" >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "Servicio no disponible: $url" >&2
    sudo docker compose ps
    exit 1
  fi
done

cat <<EOF

Demo operativa:
  ChatGPT noVNC: http://127.0.0.1:${CHATGPT_NOVNC_PORT:-6080}/vnc.html?autoconnect=1&resize=remote
  Claude noVNC:  http://127.0.0.1:${CLAUDE_NOVNC_PORT:-6081}/vnc.html?autoconnect=1&resize=remote
  Grok noVNC:    http://127.0.0.1:${GROK_NOVNC_PORT:-6082}/vnc.html?autoconnect=1&resize=remote
  Jaeger:        http://127.0.0.1:${JAEGER_UI_PORT:-16686}
  mitmweb:       http://127.0.0.1:${MITMPROXY_UI_PORT:-8081}
  Plano API:     http://127.0.0.1:${PLANO_PORT:-12000}

Contraseña VNC/mitmweb: ${VNC_PASSWORD:-plano-demo}
Ejecute: ./scripts/smoke-test.sh
EOF
