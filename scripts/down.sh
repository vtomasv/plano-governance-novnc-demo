#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${1:-}" == "--purge" ]]; then
  sudo docker compose down --volumes --remove-orphans
  echo "Pila detenida y volúmenes eliminados."
else
  sudo docker compose down --remove-orphans
  echo "Pila detenida; perfiles y CA conservados en volúmenes Docker."
fi
