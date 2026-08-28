#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/docker-lib.sh
source "$ROOT_DIR/scripts/docker-lib.sh"
init_docker_command
export DOCKER_DEFAULT_PLATFORM=linux/arm64
export PLANO_COMPOSE_PLATFORM_MODE=mac-arm64

host_os="$(uname -s)"
host_arch="$(uname -m)"
server_os="$(docker_engine version --format '{{.Server.Os}}')"
server_arch="$(docker_engine version --format '{{.Server.Arch}}')"
context="$(docker_engine context show 2>/dev/null || true)"

cat <<EOF
=== macOS / Apple Silicon ===
Host:           $host_os/$host_arch
Docker Server:  $server_os/$server_arch
Docker context: ${context:-desconocido}
Compose base:    $PLANO_COMPOSE_FILE
Compose arm64:   $ROOT_DIR/docker-compose.mac-arm64.yml
Proyecto:        $PLANO_COMPOSE_PROJECT_NAME
EOF

failures=0
if [[ "$host_os" != "Darwin" && "${ALLOW_NON_MACOS_ARM64_TEST:-0}" != "1" ]]; then
  echo "ERROR: el host no es macOS." >&2
  failures=$((failures + 1))
fi
if [[ "$host_arch" != "arm64" && "${ALLOW_NON_MACOS_ARM64_TEST:-0}" != "1" ]]; then
  echo "ERROR: el host no es Apple Silicon arm64." >&2
  failures=$((failures + 1))
fi
if [[ "$server_os" != "linux" ]]; then
  echo "ERROR: Docker Desktop no está ejecutando Linux containers." >&2
  failures=$((failures + 1))
fi
if [[ "$server_arch" != "arm64" && "$server_arch" != "aarch64" && "${ALLOW_NON_MACOS_ARM64_TEST:-0}" != "1" ]]; then
  echo "ERROR: Docker Server usa $server_arch en lugar de arm64." >&2
  failures=$((failures + 1))
fi

"$ROOT_DIR/scripts/check-runtime-ports.sh" || failures=$((failures + 1))

echo
echo "=== Arquitecturas de imágenes ==="
for service in cert-init control-center policy-guard provider-sim provider-web-sim jaeger plano governed-agent proxy-interceptor desktop-chatgpt desktop-claude desktop-grok; do
  container_id="$(docker_compose ps -aq "$service" 2>/dev/null | head -n 1 || true)"
  if [[ -z "$container_id" ]]; then
    printf 'ERROR %-24s no creado\n' "$service" >&2
    failures=$((failures + 1))
    continue
  fi
  image_id="$(docker_engine inspect "$container_id" --format '{{.Image}}')"
  image_arch="$(docker_engine image inspect "$image_id" --format '{{.Architecture}}')"
  if [[ "$image_arch" == "arm64" ]]; then
    printf 'OK    %-24s linux/%s\n' "$service" "$image_arch"
  else
    printf 'ERROR %-24s linux/%s; esperado linux/arm64\n' "$service" "$image_arch" >&2
    failures=$((failures + 1))
  fi
done

if (( failures > 0 )); then
  echo "Diagnóstico macOS: $failures fallo(s)." >&2
  exit 1
fi

echo
echo "Diagnóstico macOS M3: OK"
