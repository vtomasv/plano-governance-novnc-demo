#!/usr/bin/env bash

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
  "${DOCKER[@]}" compose "$@"
}

docker_engine() {
  "${DOCKER[@]}" "$@"
}
