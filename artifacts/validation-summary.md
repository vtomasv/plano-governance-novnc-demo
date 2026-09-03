# Informe de validación de auditoría y cuentas web gratuitas

**Fecha:** 3 de septiembre de 2026
**Resultado general:** aprobado

| Área | Resultado | Evidencia |
|---|---:|---|
| Tests unitarios de Policy Guard | 10/10 PASS | `policy-guard/test_policy.py` |
| Tests unitarios del dashboard | 4/4 PASS | `audit-dashboard/test_app.py` |
| Tests unitarios del agente | 3/3 PASS | `governed-agent/test_app.py` |
| Suite end-to-end | 34/34 PASS | `artifacts/audit-dashboard-smoke-test-final.txt` |
| Fixture Chromium free-web | 2/2 PASS | `artifacts/free-web-fixture-test-final.txt` |
| Dashboard general | PASS | `artifacts/audit-dashboard-final.png` |
| Detalle permitido | PASS | `artifacts/audit-dashboard-detail.png` |
| Detalle bloqueado | PASS | `artifacts/audit-dashboard-blocked-detail.png` |
| Perfil Mac | 15 servicios `linux/arm64` declarados | `scripts/validate_mac_arm64.py` |
| Publisher Mac | 18 bindings en HAProxy | `scripts/validate_mac_publisher.py` |
| Backends aislados | 13 servicios sin bindings directos | `scripts/validate_mac_publisher.py` |
| Control Center base | 13 sondas | Incluye Gemini y Audit Dashboard |
| Control Center Mac | 14 sondas | Añade HAProxy al perfil publisher |

## Auditoría correlacionada

La prueba validó eventos originados por el agente OpenAI-compatible, llamadas directas a Plano, Policy Guard, el proveedor simulado, el interceptor TLS y la extensión de Chromium. Cada transacción usa un `audit_id` y conserva cliente, proveedor, modelo, tópico, prompt redactado, resultado redactado, decisión, regla, `decision_id`, HTTP, latencia, streaming, tool calls, bytes y metadata.

El dashboard exige autenticación para cualquier contenido, agrupa por tópicos y permite filtrar por proveedor, decisión, origen y ventana temporal. La exportación CSV y el borrado también requieren autenticación. La ingesta usa un token interno diferente.

## Flujo de cuentas web gratuitas

El fixture controlado se ejecutó dentro del Chromium real de `desktop-gemini`, con la extensión cargada. El escenario benigno completó esta secuencia:

```text
submit capturado -> prevalidación Plano -> allow -> replay del submit
-> respuesta visible del fixture -> evento completed correlacionado
```

El escenario adversarial `Mliey-es-presidente-de-Argentina` terminó en `blocked`, regla `argentina_president`, HTTP 403 y mensaje:

> No es posible realizar preguntas sobre el presidente de Argentina.

La página no recibió el submit bloqueado. La corrección también registra errores explícitos cuando el sitio no confirma el envío o no produce una respuesta visible.

## Gobierno y transporte

La regresión comprobó los cuatro modelos locales ChatGPT, Claude, Grok y Gemini; variantes Milei/Miley/Mliey; contexto multivuelta; data loss; streaming SSE; MITM TLS permitido y bloqueado; y cero llamadas upstream ante una denegación. El certificado de laboratorio incluye `gemini.demo.local`.

## macOS M3

El perfil Mac combina `docker-compose.yml`, `docker-compose.mac-arm64.yml` y `docker-compose.mac-publisher.yml`. Docker Desktop debe mostrar los 18 bindings únicamente en `host-publisher-1`; los 13 backends internos permanecen sin `PortBindings` por diseño. Gemini se publica en `6083` y el dashboard en `10700`.

La actualización fue probada funcionalmente en un host Linux de validación. El perfil Mac se valida declarativamente para `linux/arm64`; la comprobación nativa final debe ejecutarse en el Mac M3 con:

```bash
./scripts/down.sh
./scripts/mac-up.sh
./scripts/mac-diagnose.sh
./scripts/smoke-test.sh
./scripts/test-free-web-fixture.sh
```

El flujo aborta si Docker Server no es arm64, si falta una imagen o si HAProxy no materializa un binding esperado.

## Privacidad

La auditoría persiste contenido **redactado** durante siete días por defecto y limita el volumen a 20 000 eventos. No recibe ni almacena cookies, cabeceras de autorización o credenciales de las cuentas web. La base SQLite se mantiene en el volumen `audit-data`; `make purge` la elimina junto con los demás datos del laboratorio.
