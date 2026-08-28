#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/docker-lib.sh
source "$ROOT_DIR/scripts/docker-lib.sh"
init_docker_command

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

docker_compose config >/dev/null
docker_compose config --format json > /tmp/plano-governance-compose.json
python3 scripts/validate_compose.py /tmp/plano-governance-compose.json

# Regresión: un COMPOSE_FILE heredado no debe alterar el archivo forzado por docker-lib.sh.
COMPOSE_FILE="$ROOT_DIR/dev/docker-compose.sandbox-internal.yml" \
  docker_compose config --format json > /tmp/plano-governance-compose-isolated.json
python3 scripts/validate_compose.py /tmp/plano-governance-compose-isolated.json

PLANO_COMPOSE_PLATFORM_MODE=mac-arm64 \
  docker_compose config --format json > /tmp/plano-governance-compose-mac-arm64.json
python3 scripts/validate_mac_publisher.py /tmp/plano-governance-compose-mac-arm64.json
python3 scripts/validate_mac_arm64.py /tmp/plano-governance-compose-mac-arm64.json

python3 -m pytest -q policy-guard/test_policy.py
python3 -m py_compile \
  policy-guard/app.py \
  provider-sim/app.py \
  governed-agent/app.py \
  proxy-interceptor/governance.py \
  control-center/app.py \
  scripts/validate_compose.py \
  scripts/validate_mac_arm64.py \
  scripts/validate_mac_publisher.py
node --check desktop/extension/background.js
node --check desktop/extension/content.js
bash -n scripts/*.sh desktop/start-desktop.sh proxy-interceptor/start-proxy.sh

echo "Validación estática, unitaria y de puertos: OK"
