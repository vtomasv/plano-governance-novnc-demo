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

failures=0
first_container=""

check_binding() {
  local service="$1" target_port="$2" expected_host_port="$3"
  local container_id mapping bindings origin

  container_id="$(docker_compose ps -aq "$service" 2>/dev/null | head -n 1 || true)"
  if [[ -z "$container_id" ]]; then
    printf 'ERROR %-24s contenedor no creado\n' "$service"
    failures=$((failures + 1))
    return
  fi
  [[ -z "$first_container" ]] && first_container="$container_id"

  mapping="$(docker_compose port "$service" "$target_port" 2>/dev/null || true)"
  bindings="$(docker_engine inspect "$container_id" --format '{{json .HostConfig.PortBindings}}' 2>/dev/null || true)"

  if [[ "$bindings" == *"\"${target_port}/tcp\""* && "$bindings" == *"\"HostPort\":\"${expected_host_port}\""* ]]; then
    printf 'OK    %-24s %s\n' "$service:$target_port" "${mapping:-configurado en HostConfig :$expected_host_port}"
    return
  fi

  printf 'ERROR %-24s esperado host :%s; compose-port=%s; PortBindings=%s\n' \
    "$service:$target_port" "$expected_host_port" "${mapping:-<vacío>}" "${bindings:-<vacío>}"
  failures=$((failures + 1))
}

check_binding control-center 10000 "${CONTROL_CENTER_PORT:-10000}"
check_binding desktop-chatgpt 6080 "${CHATGPT_NOVNC_PORT:-6080}"
check_binding desktop-claude 6080 "${CLAUDE_NOVNC_PORT:-6081}"
check_binding desktop-grok 6080 "${GROK_NOVNC_PORT:-6082}"
check_binding plano 12000 "${PLANO_PORT:-12000}"
check_binding plano 8001 "${PLANO_AGENT_PORT:-8001}"
check_binding plano 9901 "${PLANO_ADMIN_PORT:-19901}"
check_binding policy-guard 10500 "${POLICY_GUARD_PORT:-10500}"
check_binding provider-sim 10501 "${PROVIDER_SIM_PORT:-10501}"
check_binding provider-web-sim 8443 "${PROVIDER_TLS_PORT:-18443}"
check_binding governed-agent 10600 "${GOVERNED_AGENT_PORT:-10600}"
check_binding jaeger 16686 "${JAEGER_UI_PORT:-16686}"
check_binding jaeger 4317 "${OTLP_GRPC_PORT:-4317}"
check_binding jaeger 4318 "${OTLP_HTTP_PORT:-4318}"
check_binding proxy-interceptor 8081 "${MITMPROXY_UI_PORT:-8081}"

if [[ -n "$first_container" ]]; then
  echo
  echo "Origen Compose registrado por Docker:"
  docker_engine inspect "$first_container" \
    --format 'project={{index .Config.Labels "com.docker.compose.project"}} files={{index .Config.Labels "com.docker.compose.project.config_files"}} working_dir={{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
    2>/dev/null || true
fi

if (( failures > 0 )); then
  cat >&2 <<'EOF'

ERROR: Docker creó la pila sin todos los bindings requeridos.
Los puertos se fijan al CREAR el contenedor; pulsar Start en Docker Desktop no puede añadirlos.
Recupere la pila desde la raíz del repositorio:

  ./scripts/compose.sh down --remove-orphans
  ./scripts/up.sh

No use `docker compose run`, el botón Run sobre una imagen ni overrides externos.
EOF
  exit 1
fi

echo
echo "Bindings de runtime: OK"
