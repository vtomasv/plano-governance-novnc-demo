#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck source=scripts/docker-lib.sh
source "$ROOT_DIR/scripts/docker-lib.sh"
init_docker_command
export PLANO_COMPOSE_PLATFORM_MODE=mac-arm64

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

publisher_id="$(docker_compose ps -aq host-publisher 2>/dev/null | head -n 1 || true)"
if [[ -z "$publisher_id" ]]; then
  echo "ERROR: host-publisher no fue creado." >&2
  exit 1
fi

bindings="$(docker_engine inspect "$publisher_id" --format '{{json .HostConfig.PortBindings}}')"
status="$(docker_engine inspect "$publisher_id" --format '{{.State.Status}}')"
failures=0

if [[ "${REQUIRE_PUBLISHER_RUNNING:-1}" == "1" && "$status" != "running" ]]; then
  echo "ERROR: host-publisher existe pero su estado es '$status'; se esperaba 'running'." >&2
  failures=$((failures + 1))
fi

check_publisher_binding() {
  local target_port="$1" expected_host_port="$2" label="$3"
  if [[ "$bindings" == *"\"${target_port}/tcp\""* && "$bindings" == *"\"HostPort\":\"${expected_host_port}\""* ]]; then
    printf 'OK    %-28s 127.0.0.1:%s -> host-publisher:%s\n' "$label" "$expected_host_port" "$target_port"
  else
    printf 'ERROR %-28s falta %s -> %s; PortBindings=%s\n' "$label" "$expected_host_port" "$target_port" "$bindings" >&2
    failures=$((failures + 1))
  fi
}

check_publisher_binding 10000 "${CONTROL_CENTER_PORT:-10000}" "Control Center"
check_publisher_binding 6080 "${CHATGPT_NOVNC_PORT:-6080}" "ChatGPT noVNC"
check_publisher_binding 6081 "${CLAUDE_NOVNC_PORT:-6081}" "Claude noVNC"
check_publisher_binding 6082 "${GROK_NOVNC_PORT:-6082}" "Grok noVNC"
check_publisher_binding 6083 "${GEMINI_NOVNC_PORT:-6083}" "Gemini noVNC"
check_publisher_binding 12000 "${PLANO_PORT:-12000}" "Plano Gateway"
check_publisher_binding 8001 "${PLANO_AGENT_PORT:-8001}" "Plano Agent"
check_publisher_binding 19901 "${PLANO_ADMIN_PORT:-19901}" "Plano Admin"
check_publisher_binding 10500 "${POLICY_GUARD_PORT:-10500}" "Policy Guard"
check_publisher_binding 10501 "${PROVIDER_SIM_PORT:-10501}" "Provider Sim"
check_publisher_binding 18443 "${PROVIDER_TLS_PORT:-18443}" "Provider TLS"
check_publisher_binding 10600 "${GOVERNED_AGENT_PORT:-10600}" "Governed Agent"
check_publisher_binding 10700 "${AUDIT_DASHBOARD_PORT:-10700}" "Audit Dashboard"
check_publisher_binding 16686 "${JAEGER_UI_PORT:-16686}" "Jaeger UI"
check_publisher_binding 4317 "${OTLP_GRPC_PORT:-4317}" "OTLP gRPC"
check_publisher_binding 4318 "${OTLP_HTTP_PORT:-4318}" "OTLP HTTP"
check_publisher_binding 8081 "${MITMPROXY_UI_PORT:-8081}" "mitmweb"
check_publisher_binding 8404 "${HOST_PUBLISHER_STATS_PORT:-8404}" "HAProxy stats"

if [[ "${PUBLISHER_ONLY:-0}" == "1" ]]; then
  if (( failures > 0 )); then
    echo "Validación temprana del publisher: $failures fallo(s)." >&2
    exit 1
  fi
  echo
  echo "Publisher creado con 18 bindings: OK (estado=$status)"
  exit 0
fi

echo
echo "Comprobando ausencia de publicación directa:"
for service in control-center audit-dashboard policy-guard provider-sim provider-web-sim jaeger plano governed-agent proxy-interceptor desktop-chatgpt desktop-claude desktop-grok desktop-gemini; do
  container_id="$(docker_compose ps -aq "$service" 2>/dev/null | head -n 1 || true)"
  if [[ -z "$container_id" ]]; then
    printf 'ERROR %-28s no creado\n' "$service" >&2
    failures=$((failures + 1))
    continue
  fi
  direct="$(docker_engine inspect "$container_id" --format '{{json .HostConfig.PortBindings}}')"
  if [[ "$direct" == "{}" || "$direct" == "null" ]]; then
    printf 'OK    %-28s PortBindings=%s\n' "$service" "$direct"
  else
    printf 'ERROR %-28s tiene publicación directa: %s\n' "$service" "$direct" >&2
    failures=$((failures + 1))
  fi
done

networks="$(docker_engine inspect "$publisher_id" --format '{{json .NetworkSettings.Networks}}')"
if [[ "$networks" == *"egress"* ]]; then
  echo "ERROR: host-publisher está conectado a egress." >&2
  failures=$((failures + 1))
else
  echo "OK    host-publisher sin red egress"
fi

if (( failures > 0 )); then
  echo "Validación del publisher: $failures fallo(s)." >&2
  exit 1
fi

echo
echo "Publisher único: OK"
