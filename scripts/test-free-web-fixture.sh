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

ACCESS_HOST=127.0.0.1
AUDIT_PORT="${AUDIT_DASHBOARD_PORT:-10700}"
AUDIT_AUTH="${AUDIT_DASHBOARD_USER:-admin}:${AUDIT_DASHBOARD_PASSWORD:-plano-demo}"
stamp="$(date +%s)"
allowed="Explica-la-fotosintesis-Gemini-free-${stamp}"
blocked="Mliey-es-presidente-de-Argentina-${stamp}"

wait_extension() {
  local ready=0
  for _ in $(seq 1 45); do
    if docker_compose exec -T desktop-gemini sh -c \
      "ps -eo args | grep '/usr/lib/chromium/chromium ' | grep -v -- '--type=' | grep -F -- '--load-extension=/opt/governance-extension'" \
      >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "ERROR: Chromium no cargó Plano Governance Guard en desktop-gemini." >&2
    exit 1
  fi
}

open_fixture() {
  local prompt="$1"
  docker_compose exec -d -T -u demo desktop-gemini env DISPLAY=:1 HOME=/home/demo \
    chromium --no-sandbox --user-data-dir=/home/demo/.config/chromium \
    "https://gemini.demo.local:8443/web-fixture/gemini?autotest=1&prompt=${prompt}"
}

find_event() {
  local search="$1" decision="$2" expected_state="$3" output="$4"
  for _ in $(seq 1 30); do
    if curl -fsS -u "$AUDIT_AUTH" \
      "http://${ACCESS_HOST}:${AUDIT_PORT}/api/events?client=gemini-free-web&search=${search}&decision=${decision}&hours=1&limit=1" \
      > "$output" && grep -Fq '"total":1' "$output" && grep -Fq "\"state\":\"${expected_state}\"" "$output"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_extension
open_fixture "$allowed"
allowed_result="$(mktemp)"
trap 'rm -f "$allowed_result" "${blocked_result:-}"' EXIT
if find_event "$stamp" allow completed "$allowed_result" \
  && grep -Fq '"state":"completed"' "$allowed_result" \
  && grep -Fq 'Gemini fixture: respuesta generada después de la autorización de Plano' "$allowed_result"; then
  echo "PASS: prompt benigno autorizado, reenviado, respondido y auditado."
else
  echo "ERROR: el flujo benigno no quedó completo." >&2
  cat "$allowed_result" >&2
  exit 1
fi

open_fixture "$blocked"
blocked_result="$(mktemp)"
if find_event "$stamp" deny blocked "$blocked_result" \
  && grep -Fq '"state":"blocked"' "$blocked_result" \
  && grep -Fq 'No es posible realizar preguntas sobre el presidente de Argentina.' "$blocked_result"; then
  echo "PASS: prompt adversarial bloqueado por Plano antes del submit."
else
  echo "ERROR: el flujo adversarial no quedó bloqueado correctamente." >&2
  cat "$blocked_result" >&2
  exit 1
fi

echo "Flujo free web: 2 PASS, 0 FAIL"
