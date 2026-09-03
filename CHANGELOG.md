# Changelog

## 2.0.2 — 2026-09-03

Corrige el falso negativo de `mac-up.sh` al comprobar `host-publisher`: bajo `set -o pipefail`, `grep -q` podía cerrar la tubería después de encontrar el servicio y hacer que Docker Compose terminara con SIGPIPE (`141`). El script ahora captura primero la lista completa de servicios y valida después sobre ese valor. La sintaxis fue comprobada con Bash 3.2.

## 2.0.1 — 2026-09-03

Este hotfix corrige el caso donde `host-publisher` quedaba en estado `Created` y ninguna interfaz era visible cuando un backend tardaba en alcanzar `healthy`.

| Cambio | Resultado |
|---|---|
| Causa raíz | Eliminado `depends_on: condition: service_healthy` del publisher |
| Arranque | `mac-up.sh` crea y valida HAProxy antes de iniciar los backends |
| Fail-fast | Exige servicio, 18 bindings y estado `running` antes de continuar |
| DNS dinámico | HAProxy incorpora los backends cuando se vuelven disponibles |
| Regresión | El validador prohíbe dependencias futuras en `host-publisher` |
| Prueba | Publisher iniciado sin backends; 18 bindings y stats HTTP 200 |

## 2.0.0 — 2026-09-03

Esta versión incorpora auditoría correlacionada de contenido y corrige el ciclo asíncrono de las cuentas web gratuitas.

| Cambio | Resultado |
|---|---|
| Dashboard | Nueva UI autenticada en `10700` con prompt, resultado, regla, latencia, modelo, streaming, tool calls y metadata |
| Tópicos | Clasificación local y agrupación por política, seguridad, programación, ciencia, finanzas, soporte, salud y redacción |
| Correlación | `audit_id` estable entre agente, Policy Guard, proveedor, proxy TLS y extensión |
| Privacidad | Redacción antes de persistir, retención de 7 días, límite de eventos y ausencia de cookies/Authorization |
| Gemini | Cuarto escritorio noVNC en `6083`, modelo local, SAN TLS, proxy y extensión actualizados |
| Free web | La extensión extrae solo el compositor, espera Plano, reenvía el submit autorizado y captura la respuesta DOM |
| Errores | Estados explícitos `provider_send_not_confirmed` y `provider_response_timeout` en lugar de espera silenciosa |
| Publisher Mac | Quince servicios arm64 declarados, dieciocho bindings en HAProxy y trece backends sin publicación directa |
| Validación | 34/34 pruebas end-to-end, 2/2 pruebas del Chromium real y 17/17 pruebas unitarias |

## 1.3.0 — 2026-08-27

Esta versión adopta la estrategia de **publisher único HAProxy** para macOS Apple Silicon. Los escritorios y servicios internos dejan de publicar puertos individualmente; Docker Desktop muestra todos los bindings en `host-publisher-1`.

| Cambio | Resultado |
|---|---|
| Publisher | HAProxy 3.2.22 arm64, fijado por digest y limitado a loopback |
| noVNC | `6080`, `6081` y `6082` atraviesan TCP/WebSocket sin terminación ni reescritura |
| Aislamiento | Once servicios con `PortBindings={}`; escritorios solo en `control` |
| Egress | `host-publisher` no pertenece a la red `egress`; Plano y el proxy conservan la salida gobernada |
| Diagnóstico | `check-publisher-ports.sh`, HAProxy stats en `8404` y tarjeta en Control Center |
| Validación | Trece imágenes arm64, dieciséis bindings, WebSocket `101` y 23/23 pruebas funcionales |

## 1.2.0 — 2026-08-27

Esta versión convierte **macOS Apple Silicon** en una plataforma validada de forma explícita y corrige la recomendación errónea de PowerShell para un Mac M3.

| Cambio | Resultado |
|---|---|
| Arranque Mac | Nuevo `scripts/mac-up.sh`, invocado automáticamente por `up.sh` en Darwin/arm64 |
| Plataforma | Override `docker-compose.mac-arm64.yml` con `linux/arm64` en todos los servicios |
| Imágenes externas | Manifests arm64 fijados para Nginx y Jaeger |
| Preflight | Verifica `uname`, Docker Server, contexto, puertos ocupados y Compose efectivo |
| Diagnóstico | Nuevo `scripts/mac-diagnose.sh` con arquitectura y bindings por servicio |
| Evidencia | Doce imágenes arm64, quince bindings y 23/23 pruebas funcionales |
| Documentación | Guía dedicada `docs/MACOS-APPLE-SILICON.md`; PowerShell deja de ser la ruta principal |

## 1.1.1 — 2026-08-27

Esta revisión corrige el caso observado en Docker Desktop donde los contenedores aparecían activos pero solo Plano conservaba puertos publicados.

| Cambio | Resultado |
|---|---|
| Compose efectivo | Los scripts fuerzan la ruta absoluta de `docker-compose.yml` e ignoran `COMPOSE_FILE` heredado |
| Recreación | El arranque utiliza `--force-recreate`; no reutiliza contenedores creados sin bindings |
| Fail-fast | `check-runtime-ports.sh` valida `HostConfig.PortBindings` para todas las superficies |
| Docker Desktop | Nuevos `up.ps1`, `down.ps1` y `diagnose.ps1` nativos de PowerShell |
| Origen | El diagnóstico muestra proyecto, directorio y archivos Compose registrados en las etiquetas Docker |
| Cobertura | Se prueba un estado contaminado con `PortBindings={}` y su recuperación completa |
| Bindings adicionales | También se verifican `18443`, `4317` y `4318` |

## 1.1.0 — 2026-08-27

Esta versión corrige la experiencia de despliegue y diagnóstico en estaciones de trabajo.

| Cambio | Resultado |
|---|---|
| Puertos noVNC | Se validan y materializan `6080`, `6081` y `6082` en el Compose principal |
| Override interno | Se movió a `dev/` y ahora exige una variable de habilitación para impedir uso accidental |
| Control Center | Nuevo panel en `http://127.0.0.1:10000` con 11 sondas internas y enlaces operativos |
| Plano | Healthcheck en `/healthz`; Envoy Admin `19901` documentado como diagnóstico |
| mitmweb | Contraseña separada en `MITMWEB_PASSWORD`; login probado automáticamente |
| Servicios auxiliares | Índices JSON para Policy Guard y Provider Sim; healthchecks para Jaeger y upstream TLS |
| Diagnóstico | Nuevo `scripts/diagnose.sh` y validación automática de PortBindings |
| Portabilidad | Scripts compatibles con Docker Desktop y Linux, con uso condicional de `sudo` |
| Pruebas | Suite ampliada de 16 a 23 comprobaciones end-to-end; resultado 23 PASS, 0 FAIL |

## 1.0.0 — 2026-08-27

Versión inicial de la demo con Plano, noVNC, filtro de gobierno, proxy TLS controlado, proveedor simulado y Jaeger.
