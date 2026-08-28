#!/usr/bin/env bash

PLANO_DEMO_ROOT="${PLANO_DEMO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PLANO_COMPOSE_FILE="${PLANO_DEMO_ROOT}/docker-compose.yml"
PLANO_COMPOSE_PROJECT_NAME="${PLANO_COMPOSE_PROJECT_NAME:-$(basename "$PLANO_DEMO_ROOT")}"

init_docker_command() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker no está instalado o no está en PATH." >&2
    return 1
  fi

  DOCKER=(docker)
  if docker info >/dev/null 2>&1; then
    return 0
  fi

  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
    return 0
  fi

  echo "ERROR: Docker Engine no responde. Inicie Docker Desktop/Engine o habilite acceso al daemon." >&2
  return 1
}

docker_compose() {
  # `-f` explícito tiene precedencia sobre COMPOSE_FILE y evita overrides heredados.
  if [[ "${PLANO_COMPOSE_PLATFORM_MODE:-}" == "mac-arm64" ]]; then
    docker_compose_mac_arm64 "$@"
    return
  fi
  "${DOCKER[@]}" compose \
    --project-directory "$PLANO_DEMO_ROOT" \
    --project-name "$PLANO_COMPOSE_PROJECT_NAME" \
    -f "$PLANO_COMPOSE_FILE" \
    "$@"
}

docker_compose_real_api() {
  "${DOCKER[@]}" compose \
    --project-directory "$PLANO_DEMO_ROOT" \
    --project-name "$PLANO_COMPOSE_PROJECT_NAME" \
    -f "$PLANO_COMPOSE_FILE" \
    -f "${PLANO_DEMO_ROOT}/docker-compose.real-api.yml" \
    "$@"
}

docker_compose_mac_arm64() {
  "${DOCKER[@]}" compose \
    --project-directory "$PLANO_DEMO_ROOT" \
    --project-name "$PLANO_COMPOSE_PROJECT_NAME" \
    -f "$PLANO_COMPOSE_FILE" \
    -f "${PLANO_DEMO_ROOT}/docker-compose.mac-arm64.yml" \
    "$@"
}

docker_engine() {
  "${DOCKER[@]}" "$@"
}
