#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" && "${PLANO_MAC_DIAG_DISPATCHED:-0}" != "1" ]]; then
  exec env PLANO_MAC_DIAG_DISPATCHED=1 "$ROOT_DIR/scripts/mac-diagnose.sh"
fi

# shellcheck source=scripts/docker-lib.sh
source "$ROOT_DIR/scripts/docker-lib.sh"
init_docker_command

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BIND_ADDRESS="${BIND_ADDRESS:-127.0.0.1}"
CONTROL_CENTER_PORT="${CONTROL_CENTER_PORT:-10000}"
CHATGPT_NOVNC_PORT="${CHATGPT_NOVNC_PORT:-6080}"
CLAUDE_NOVNC_PORT="${CLAUDE_NOVNC_PORT:-6081}"
GROK_NOVNC_PORT="${GROK_NOVNC_PORT:-6082}"
GEMINI_NOVNC_PORT="${GEMINI_NOVNC_PORT:-6083}"
AUDIT_DASHBOARD_PORT="${AUDIT_DASHBOARD_PORT:-10700}"
PLANO_PORT="${PLANO_PORT:-12000}"
PLANO_AGENT_PORT="${PLANO_AGENT_PORT:-8001}"
PLANO_ADMIN_PORT="${PLANO_ADMIN_PORT:-19901}"
POLICY_GUARD_PORT="${POLICY_GUARD_PORT:-10500}"
PROVIDER_SIM_PORT="${PROVIDER_SIM_PORT:-10501}"
GOVERNED_AGENT_PORT="${GOVERNED_AGENT_PORT:-10600}"
JAEGER_UI_PORT="${JAEGER_UI_PORT:-16686}"
MITMPROXY_UI_PORT="${MITMPROXY_UI_PORT:-8081}"
VNC_PASSWORD="${VNC_PASSWORD:-plano-demo}"
MITMWEB_PASSWORD="${MITMWEB_PASSWORD:-plano-demo}"

host_for_url="$BIND_ADDRESS"
[[ "$host_for_url" == "0.0.0.0" ]] && host_for_url="127.0.0.1"

printf '\n=== Versiones ===\n'
"${DOCKER[@]}" version --format 'Docker Engine: {{.Server.Version}}'
"${DOCKER[@]}" compose version

printf '\n=== Validación del Compose principal ===\n'
if [[ -n "${COMPOSE_FILE:-}" ]]; then
  echo "Aviso: COMPOSE_FILE=$COMPOSE_FILE está definido, pero será ignorado por estos scripts."
fi
docker_compose config --quiet
echo "Compose válido. No use dev/docker-compose.sandbox-internal.yml en su estación."

printf '\n=== Estado de contenedores ===\n'
docker_compose ps -a

printf '\n=== Mapeos de puertos efectivos ===\n'
for item in \
  'control-center:10000' \
  'desktop-chatgpt:6080' \
  'desktop-claude:6080' \
  'desktop-grok:6080' \
  'desktop-gemini:6080' \
  'audit-dashboard:10700' \
  'plano:12000' \
  'plano:8001' \
  'plano:9901' \
  'policy-guard:10500' \
  'provider-sim:10501' \
  'provider-web-sim:8443' \
  'governed-agent:10600' \
  'jaeger:16686' \
  'jaeger:4317' \
  'jaeger:4318' \
  'proxy-interceptor:8081'; do
  service="${item%%:*}"
  target="${item##*:}"
  mapping="$(docker_compose port "$service" "$target" 2>/dev/null || true)"
  if [[ -n "$mapping" ]]; then
    printf 'OK    %-24s %s -> %s\n' "$service:$target" "$mapping" "$target"
  else
    printf 'FALTA %-24s sin publicación; revise si el contenedor está creado/activo.\n' "$service:$target"
  fi
done

origin_id="$(docker_compose ps -q plano 2>/dev/null || true)"
if [[ -n "$origin_id" ]]; then
  printf '\n=== Origen de la pila registrado en Docker ===\n'
  docker_engine inspect "$origin_id" \
    --format 'project={{index .Config.Labels "com.docker.compose.project"}} files={{index .Config.Labels "com.docker.compose.project.config_files"}} working_dir={{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
    2>/dev/null || true
fi

check_url() {
  local label="$1" url="$2" expected="${3:-2}"
  local code
  code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$url" || true)"
  if [[ "$code" == "$expected"* ]]; then
    printf 'OK    %-26s HTTP %s  %s\n' "$label" "$code" "$url"
    return 0
  fi
  printf 'ERROR %-26s HTTP %s  %s\n' "$label" "${code:-000}" "$url"
  return 1
}

printf '\n=== Comprobaciones HTTP ===\n'
failures=0
check_url 'Control Center' "http://$host_for_url:$CONTROL_CENTER_PORT/health" || failures=$((failures+1))
check_url 'ChatGPT noVNC' "http://$host_for_url:$CHATGPT_NOVNC_PORT/vnc.html" || failures=$((failures+1))
check_url 'Claude noVNC' "http://$host_for_url:$CLAUDE_NOVNC_PORT/vnc.html" || failures=$((failures+1))
check_url 'Grok noVNC' "http://$host_for_url:$GROK_NOVNC_PORT/vnc.html" || failures=$((failures+1))
check_url 'Gemini noVNC' "http://$host_for_url:$GEMINI_NOVNC_PORT/vnc.html" || failures=$((failures+1))
check_url 'Audit Dashboard' "http://$host_for_url:$AUDIT_DASHBOARD_PORT/health" || failures=$((failures+1))
check_url 'Plano Gateway' "http://$host_for_url:$PLANO_PORT/healthz" || failures=$((failures+1))
check_url 'Plano Admin' "http://$host_for_url:$PLANO_ADMIN_PORT/ready" || failures=$((failures+1))
check_url 'Policy Guard' "http://$host_for_url:$POLICY_GUARD_PORT/health" || failures=$((failures+1))
check_url 'Provider Sim' "http://$host_for_url:$PROVIDER_SIM_PORT/health" || failures=$((failures+1))
check_url 'Governed Agent' "http://$host_for_url:$GOVERNED_AGENT_PORT/health" || failures=$((failures+1))
check_url 'Jaeger' "http://$host_for_url:$JAEGER_UI_PORT/" || failures=$((failures+1))
# mitmweb responde 403 antes del login; eso confirma que la UI está activa.
mitm_code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://$host_for_url:$MITMPROXY_UI_PORT/" || true)"
if [[ "$mitm_code" =~ ^(200|302|401|403)$ ]]; then
  printf 'OK    %-26s HTTP %s  %s\n' 'mitmweb' "$mitm_code" "http://$host_for_url:$MITMPROXY_UI_PORT/"
else
  printf 'ERROR %-26s HTTP %s  %s\n' 'mitmweb' "${mitm_code:-000}" "http://$host_for_url:$MITMPROXY_UI_PORT/"
  failures=$((failures+1))
fi

cat <<EOF

=== Accesos ===
Control Center: http://$host_for_url:$CONTROL_CENTER_PORT/
ChatGPT noVNC:  http://$host_for_url:$CHATGPT_NOVNC_PORT/vnc.html?autoconnect=1&resize=remote
Claude noVNC:   http://$host_for_url:$CLAUDE_NOVNC_PORT/vnc.html?autoconnect=1&resize=remote
Grok noVNC:     http://$host_for_url:$GROK_NOVNC_PORT/vnc.html?autoconnect=1&resize=remote
Gemini noVNC:   http://$host_for_url:$GEMINI_NOVNC_PORT/vnc.html?autoconnect=1&resize=remote
Auditoría LLM:  http://$host_for_url:$AUDIT_DASHBOARD_PORT/
Plano Admin:    http://$host_for_url:$PLANO_ADMIN_PORT/
mitmweb:        http://$host_for_url:$MITMPROXY_UI_PORT/
Jaeger:         http://$host_for_url:$JAEGER_UI_PORT/

Contraseña noVNC:  $VNC_PASSWORD
Dashboard:          ${AUDIT_DASHBOARD_USER:-admin} / ${AUDIT_DASHBOARD_PASSWORD:-plano-demo}
Contraseña mitmweb: $MITMWEB_PASSWORD
EOF

if (( failures > 0 )); then
  cat >&2 <<EOF

Se detectaron $failures comprobaciones fallidas.
Use:
  ./scripts/compose.sh logs --tail=200 <servicio>
  ./scripts/up.sh
EOF
  exit 1
fi

echo "Diagnóstico completado: todos los endpoints esperados responden."
