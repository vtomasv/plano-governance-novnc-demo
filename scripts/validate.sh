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

"${DOCKER[@]}" compose config >/dev/null
"${DOCKER[@]}" compose config --format json > /tmp/plano-governance-compose.json
python3 scripts/validate_compose.py /tmp/plano-governance-compose.json
python3 -m pytest -q policy-guard/test_policy.py
python3 -m py_compile \
  policy-guard/app.py \
  provider-sim/app.py \
  governed-agent/app.py \
  proxy-interceptor/governance.py \
  control-center/app.py
node --check desktop/extension/background.js
node --check desktop/extension/content.js
bash -n scripts/*.sh desktop/start-desktop.sh proxy-interceptor/start-proxy.sh

echo "Validación estática, unitaria y de puertos: OK"
