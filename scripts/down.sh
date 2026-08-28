#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/docker-lib.sh
source "$ROOT_DIR/scripts/docker-lib.sh"
init_docker_command

if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
  export PLANO_COMPOSE_PLATFORM_MODE=mac-arm64
fi

if [[ "${1:-}" == "--purge" ]]; then
  docker_compose down --volumes --remove-orphans
  echo "Pila detenida y volúmenes eliminados."
else
  docker_compose down --remove-orphans
  echo "Pila detenida; perfiles y CA conservados en volúmenes Docker."
fi
