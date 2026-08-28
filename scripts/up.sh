#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/docker-lib.sh
source "$ROOT_DIR/scripts/docker-lib.sh"
init_docker_command

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Se creó .env desde .env.example"
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

BIND_ADDRESS="${BIND_ADDRESS:-127.0.0.1}"
ACCESS_HOST="$BIND_ADDRESS"
[[ "$ACCESS_HOST" == "0.0.0.0" ]] && ACCESS_HOST="127.0.0.1"

if [[ -n "${COMPOSE_FILE:-}" ]]; then
  echo "Aviso: COMPOSE_FILE está definido, pero será ignorado; se usará exclusivamente $PLANO_COMPOSE_FILE"
fi

docker_compose config --quiet
docker_compose up --build --detach --remove-orphans --force-recreate
"$ROOT_DIR/scripts/check-runtime-ports.sh"

for url in \
  "http://${ACCESS_HOST}:${CONTROL_CENTER_PORT:-10000}/health" \
  "http://${ACCESS_HOST}:${PLANO_PORT:-12000}/healthz" \
  "http://${ACCESS_HOST}:${PLANO_ADMIN_PORT:-19901}/ready" \
  "http://${ACCESS_HOST}:${GOVERNED_AGENT_PORT:-10600}/health" \
  "http://${ACCESS_HOST}:${CHATGPT_NOVNC_PORT:-6080}/vnc.html" \
  "http://${ACCESS_HOST}:${CLAUDE_NOVNC_PORT:-6081}/vnc.html" \
  "http://${ACCESS_HOST}:${GROK_NOVNC_PORT:-6082}/vnc.html"; do
  ready=0
  for _ in $(seq 1 90); do
    if curl -fsS "$url" >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "Servicio no disponible: $url" >&2
    docker_compose ps
    exit 1
  fi
done

cat <<EOF

Demo operativa:
  Control Center: http://${ACCESS_HOST}:${CONTROL_CENTER_PORT:-10000}/
  ChatGPT noVNC: http://${ACCESS_HOST}:${CHATGPT_NOVNC_PORT:-6080}/vnc.html?autoconnect=1&resize=remote
  Claude noVNC:  http://${ACCESS_HOST}:${CLAUDE_NOVNC_PORT:-6081}/vnc.html?autoconnect=1&resize=remote
  Grok noVNC:    http://${ACCESS_HOST}:${GROK_NOVNC_PORT:-6082}/vnc.html?autoconnect=1&resize=remote
  Jaeger:        http://${ACCESS_HOST}:${JAEGER_UI_PORT:-16686}
  mitmweb:       http://${ACCESS_HOST}:${MITMPROXY_UI_PORT:-8081}
  Plano API:     http://${ACCESS_HOST}:${PLANO_PORT:-12000}
  Plano Admin:   http://${ACCESS_HOST}:${PLANO_ADMIN_PORT:-19901}/

Contraseña noVNC:   ${VNC_PASSWORD:-plano-demo}
Contraseña mitmweb: ${MITMWEB_PASSWORD:-plano-demo}

Configuración:
  Puertos/contraseñas: .env
  Plano:                plano/config.local.yaml
  Política:             policy-guard/app.py

Ejecute: ./scripts/diagnose.sh
Pruebas: ./scripts/smoke-test.sh
EOF
