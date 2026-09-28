# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

Demo de gobierno de shadow AI con Plano (`katanemo/plano:0.4.36`). Cuatro escritorios Chromium accesibles por noVNC (ChatGPT, Claude, Grok, Gemini) fuerzan todo su HTTPS por un proxy mitmproxy con una CA de laboratorio; **Plano es el único que decide** si un prompt continúa. La regla de la demo bloquea preguntas sobre el presidente de Argentina (tolerante a variantes como `Miley`/`Mliey`, leetspeak, contexto dividido entre turnos) y devuelve HTTP 403 con el mensaje fijo `No es posible realizar preguntas sobre el presidente de Argentina.` También bloquea fugas de secretos (`api_key=...`). La documentación del proyecto está en español; mantenga ese idioma en docs, mensajes y comentarios.

## Comandos

```bash
make up            # ./scripts/up.sh (en Mac arm64 delega a mac-up.sh)
make mac-up        # ruta principal en Apple Silicon (host-publisher primero)
make down          # detiene conservando perfiles y CA
make purge         # elimina también perfiles, cookies, CA y volúmenes
make validate      # validación estática + pytest + py_compile + node --check + bash -n (no requiere stack arriba)
make test          # scripts/smoke-test.sh: E2E contra el stack levantado (34 checks)
make ports         # check-publisher-ports.sh (Mac arm64) o check-runtime-ports.sh
make diagnose      # mac-diagnose.sh o diagnose.sh según plataforma
make logs          # logs de plano, policy-guard, proxy-interceptor, governed-agent
make certs         # genera la CA en ./certs
make ollama        # prepara el Ollama nativo del host (modelo de analítica)
```

Test unitario individual (cada servicio tiene su propio `test_*.py`, se ejecuta desde su directorio):

```bash
(cd policy-guard && python3 -m pytest -q test_policy.py -k <nombre>)
(cd audit-dashboard && python3 -m pytest -q test_app.py)
(cd governed-agent && python3 -m pytest -q test_app.py)
```

APIs reales (opcional): exportar `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROK_API_KEY` y añadir `-f docker-compose.real-api.yml` (usa `plano/config.real-api.yaml`).

Utilice siempre `scripts/compose.sh` / `scripts/docker-lib.sh` (`docker_compose`) en lugar de `docker compose` directo: fuerzan los archivos Compose correctos e ignoran un `COMPOSE_FILE` heredado.

## Arquitectura

Flujo de un prompt: extensión de Chromium (prevalida el texto del compositor, `desktop/extension/`) → proxy `proxy-interceptor` (mitmproxy + addon `governance.py`, solo inspecciona conversaciones en hosts gobernados, no reenvía cookies/tokens) → preflight a Plano `:12000` → input filter HTTP `policy-guard :10500` (inspecciona todo el historial de usuario; deny → 403 sin llamar al proveedor; allow → `provider-sim :10501` o proveedor real). Si Plano falla, `POLICY_FAIL_MODE=closed` bloquea. `governed-agent` es un agente FastAPI OpenAI-compatible cuya única salida LLM es `PLANO_BASE_URL`. Plano exporta trazas OTLP a Jaeger. `audit-dashboard` (SQLite) recibe eventos correlacionados del agente, filtro, proxy y proveedor con token de ingesta; redacta secretos, nunca guarda el cuerpo del prompt sin redactar (solo SHA-256). `control-center` es la UI de estado/operación.

Configuración de Plano: `plano/config.local.yaml` (listener `model` en 12000 con `input_filters`, listener `agent` en 8001, proveedores `custom/local-*`, alias `*-demo`). Para cambiar routing/filtros edite ese YAML y recree `plano`; el Envoy Admin (`:19901`) solo inspecciona.

### Redes y publicación de puertos (crítico)

Cuatro redes Docker: `control` y `upstream-sim` internas; solo `proxy-interceptor` y Plano tocan `egress`; los escritorios solo están en `control` (sin salida directa ni bindings). En la ruta Mac (`docker-compose.mac-arm64.yml` + `docker-compose.mac-publisher.yml`) **todos los 18 bindings viven únicamente en `host-publisher`** (HAProxy TCP passthrough, `host-publisher/haproxy.cfg`, sin red egress); el resto de contenedores debe tener `PortBindings={}`. Por eso:

- `mac-up.sh` crea/inicia `host-publisher` primero y falla si falta una imagen arm64 o un binding.
- No use `docker compose run`, "Run" de Docker Desktop ni solo "Start" sobre contenedores creados sin puertos: los bindings se asignan al crear/recrear.
- `dev/docker-compose.sandbox-internal.yml` es un workaround para kernels sin netfilter anidado y elimina `ports`; no usarlo en estaciones normales.
- `scripts/validate_compose.py`, `validate_mac_publisher.py` y `validate_mac_arm64.py` verifican estas invariantes sobre el `compose config --format json`; actualícelos si cambia la topología.

Credenciales de laboratorio por defecto en `.env` (no versionado; plantilla `.env.example`): `VNC_PASSWORD`, `MITMWEB_PASSWORD`, `AUDIT_DASHBOARD_PASSWORD` = `plano-demo`, usuario del dashboard `admin`. `BIND_ADDRESS=127.0.0.1` evita exponer la superficie fuera del host. La CA privada solo debe existir dentro de contenedores (volumen `demo-certs`); nunca copiarla al host ni versionarla.

### Reglas dinámicas y analítica (ADR-004)

- Las reglas ya **no están en código**: viven en SQLite del `audit-dashboard` (`rules_store.py`, UI en `/rules`). `policy-guard/engine.py` las compila y evalúa; `default_rules.py` solo siembra la primera vez y sirve de respaldo. El dashboard valida cada borrador contra el guard (`/admin/test`), guarda, y llama a `/admin/reload`; el guard además sondea `/policy/rules` cada 5 s. Los ids de regla (`argentina_president`, `assigned_secret`…) son el `code` del error 403 y los usan tests y smoke.
- Los handlers `async` del dashboard que llaman al guard deben usar `run_in_threadpool`; si no, el guard, al recargar, vuelve a llamar al dashboard y hay un deadlock de 3 s.
- `audit-dashboard/analytics.py` clasifica prompts con Ollama (`ANALYTICS_MODEL`, por defecto `qwen2.5:7b-instruct`) en un worker en segundo plano y agrega para `/usage`. Ollama corre **nativo en el Mac**; llega por `host-publisher:11434` (HAProxy) a través de la red interna `analytics` (172.31.240.0/28), sin publicar puerto en el host. Si cambia el prompt de clasificación, use *Reanalizar todo*.
- Los Dockerfile copian módulos explícitos (`COPY app.py engine.py default_rules.py`, `COPY app.py analytics.py rules_store.py`): añada aquí cualquier módulo nuevo.

## Documentación

`docs/ADR-00{1,2,3,4}-*.md` (arquitectura, host-publisher, dashboard, reglas y analítica), `docs/OPERATIONS.md`, `docs/MACOS-APPLE-SILICON.md`, `docs/AUDIT-DASHBOARD.md`, y `CHANGELOG.md`. `artifacts/` contiene evidencia de validaciones (capturas, salidas de smoke tests), no código.
