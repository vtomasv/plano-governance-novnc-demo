#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/docker-lib.sh
source "$ROOT_DIR/scripts/docker-lib.sh"
init_docker_command

host_os="$(uname -s)"
host_arch="$(uname -m)"
if [[ "$host_os" != "Darwin" && "${ALLOW_NON_MACOS_ARM64_TEST:-0}" != "1" ]]; then
  echo "ERROR: este script es exclusivo de macOS; sistema detectado: $host_os." >&2
  exit 1
fi
if [[ "$host_arch" != "arm64" && "${ALLOW_NON_MACOS_ARM64_TEST:-0}" != "1" ]]; then
  echo "ERROR: se requiere Apple Silicon arm64; arquitectura detectada: $host_arch." >&2
  exit 1
fi

server_os="$(docker_engine version --format '{{.Server.Os}}')"
server_arch="$(docker_engine version --format '{{.Server.Arch}}')"
context="$(docker_engine context show 2>/dev/null || true)"
if [[ "$server_os" != "linux" ]]; then
  echo "ERROR: Docker Desktop debe ejecutar Linux containers; servidor detectado: $server_os/$server_arch." >&2
  exit 1
fi
if [[ "$server_arch" != "arm64" && "$server_arch" != "aarch64" && "${ALLOW_NON_MACOS_ARM64_TEST:-0}" != "1" ]]; then
  echo "ERROR: Docker Server no es arm64 ($server_arch). Use Docker Desktop para Apple Silicon, no una instalación Intel." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Se creó .env desde .env.example"
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

export DOCKER_DEFAULT_PLATFORM=linux/arm64
export PLANO_COMPOSE_PLATFORM_MODE=mac-arm64
export PLANO_MAC_DISPATCHED=1

cat <<EOF
Preflight macOS Apple Silicon:
  Host:             $host_os/$host_arch
  Docker Server:    $server_os/$server_arch
  Docker context:   ${context:-desconocido}
  Plataforma build: $DOCKER_DEFAULT_PLATFORM
  Compose base:     $PLANO_COMPOSE_FILE
  Compose arm64:    $ROOT_DIR/docker-compose.mac-arm64.yml
  Publisher Mac:    $ROOT_DIR/docker-compose.mac-publisher.yml
EOF

# Elimina contenedores obsoletos del mismo proyecto; conserva perfiles y CA.
docker_compose down --remove-orphans

# En Mac, lsof permite detectar conflictos antes de esperar una construcción larga.
if command -v lsof >/dev/null 2>&1; then
  for port in \
    "${CONTROL_CENTER_PORT:-10000}" \
    "${CHATGPT_NOVNC_PORT:-6080}" \
    "${CLAUDE_NOVNC_PORT:-6081}" \
    "${GROK_NOVNC_PORT:-6082}" \
    "${GEMINI_NOVNC_PORT:-6083}" \
    "${PLANO_PORT:-12000}" \
    "${PLANO_AGENT_PORT:-8001}" \
    "${PLANO_ADMIN_PORT:-19901}" \
    "${POLICY_GUARD_PORT:-10500}" \
    "${PROVIDER_SIM_PORT:-10501}" \
    "${GOVERNED_AGENT_PORT:-10600}" \
    "${AUDIT_DASHBOARD_PORT:-10700}" \
    "${JAEGER_UI_PORT:-16686}" \
    "${OTLP_GRPC_PORT:-4317}" \
    "${OTLP_HTTP_PORT:-4318}" \
    "${MITMPROXY_UI_PORT:-8081}" \
    "${PROVIDER_TLS_PORT:-18443}" \
    "${HOST_PUBLISHER_STATS_PORT:-8404}"; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "ERROR: el puerto $port ya está ocupado:" >&2
      lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
      echo "Cambie el puerto correspondiente en .env o detenga el proceso." >&2
      exit 1
    fi
  done
fi

pull_external_arm64_images() {
  docker_engine pull --platform linux/arm64 nginx:1.28.0-alpine@sha256:e8552debd77891036e8928d45f6f6e6d9eee56ce720668c0cdd723f963c3a5c5
  docker_engine pull --platform linux/arm64 jaegertracing/all-in-one:1.68.0@sha256:6e1935c81a7ecfe7a2355e7ddcf418ec0d751fd30e8f1b4e9b0df25d6040ee2a
  docker_engine pull --platform linux/arm64 haproxy:3.2.22-alpine@sha256:cfb14fccb3ea107a99ea7d49716ede401466b6d6721409fb1503eea5a024c438
}

verify_container_architectures() {
  local service container_id image_id image_arch failures=0
  for service in cert-init control-center audit-dashboard policy-guard provider-sim provider-web-sim jaeger plano governed-agent proxy-interceptor desktop-chatgpt desktop-claude desktop-grok desktop-gemini host-publisher; do
    container_id="$(docker_compose ps -aq "$service" 2>/dev/null | head -n 1 || true)"
    if [[ -z "$container_id" ]]; then
      echo "ERROR: no se creó $service." >&2
      failures=$((failures + 1))
      continue
    fi
    image_id="$(docker_engine inspect "$container_id" --format '{{.Image}}')"
    image_arch="$(docker_engine image inspect "$image_id" --format '{{.Architecture}}')"
    if [[ "$image_arch" == "arm64" ]]; then
      printf 'OK    %-24s linux/%s\n' "$service" "$image_arch"
    else
      printf 'ERROR %-24s arquitectura linux/%s; se esperaba linux/arm64\n' "$service" "$image_arch" >&2
      failures=$((failures + 1))
    fi
  done
  (( failures == 0 ))
}

pull_external_arm64_images

# Materializar primero el único borde del host. Sin dependencias de salud,
# HAProxy puede quedar escuchando mientras los backends terminan de arrancar.
if ! docker_compose config --services | grep -Fxq 'host-publisher'; then
  echo "ERROR: el Compose efectivo no contiene host-publisher." >&2
  echo "Archivos esperados: docker-compose.yml + docker-compose.mac-arm64.yml + docker-compose.mac-publisher.yml" >&2
  exit 1
fi

docker_compose create --force-recreate host-publisher
PUBLISHER_ONLY=1 REQUIRE_PUBLISHER_RUNNING=0 \
  "$ROOT_DIR/scripts/check-publisher-ports.sh"
docker_compose start host-publisher
publisher_id="$(docker_compose ps -q host-publisher)"
if [[ -z "$publisher_id" || "$(docker_engine inspect "$publisher_id" --format '{{.State.Status}}')" != "running" ]]; then
  echo "ERROR: host-publisher no pudo iniciar." >&2
  docker_compose ps -a host-publisher >&2 || true
  docker_compose logs --tail=100 host-publisher >&2 || true
  exit 1
fi

echo "host-publisher creado y ejecutándose antes de iniciar los backends."

if [[ "${MAC_VALIDATE_ONLY:-0}" == "1" ]]; then
  docker_compose build --pull
  docker_compose create --force-recreate
  REQUIRE_PUBLISHER_RUNNING=0 "$ROOT_DIR/scripts/check-publisher-ports.sh"
  verify_container_architectures
  echo "Validación macOS/arm64 completada sin iniciar la pila."
  exit 0
fi

"$ROOT_DIR/scripts/up.sh"

echo
verify_container_architectures
cat <<EOF

Validación macOS M3: OK
Abra Control Center: http://127.0.0.1:${CONTROL_CENTER_PORT:-10000}/
Dashboard auditoría: http://127.0.0.1:${AUDIT_DASHBOARD_PORT:-10700}/
Gemini noVNC:       http://127.0.0.1:${GEMINI_NOVNC_PORT:-6083}/vnc.html?autoconnect=1&resize=remote
Estado HAProxy:      http://127.0.0.1:${HOST_PUBLISHER_STATS_PORT:-8404}/
EOF
