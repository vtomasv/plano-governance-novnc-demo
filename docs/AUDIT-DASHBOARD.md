# Dashboard de auditoría LLM

El servicio `audit-dashboard` reúne en una única transacción la solicitud del cliente, la decisión de Plano y el resultado del proveedor. Su objetivo es permitir una demostración clara de **qué prompt se evaluó, por qué se permitió o bloqueó y qué respuesta produjo**, sin almacenar cookies, cabeceras de autorización ni credenciales de cuentas web.

## Acceso

En macOS Apple Silicon, HAProxy publica el dashboard exclusivamente sobre loopback:

```text
http://127.0.0.1:10700/
```

La autenticación predeterminada usa el usuario `admin` y la contraseña `plano-demo`. Ambos valores se cambian en `.env` mediante `AUDIT_DASHBOARD_USER` y `AUDIT_DASHBOARD_PASSWORD`. El token `AUDIT_INGEST_TOKEN` protege la API interna de ingesta y no debe coincidir con la contraseña de usuario en producción.

| Superficie | Acceso | Propósito |
|---|---|---|
| `/` | Autenticación Basic | Dashboard interactivo |
| `/api/events` | Autenticación Basic | Búsqueda y filtros |
| `/api/events/{audit_id}` | Autenticación Basic | Prompt, resultado y metadata completos |
| `/api/summary` | Autenticación Basic | Métricas, tópicos y actividad temporal |
| `/api/export.csv` | Autenticación Basic | Exportación operativa |
| `/ingest` | `x-audit-token` | Ingesta interna correlacionada |
| `/correlate` | `x-audit-token` | Correlación por proveedor y hash de prompt |
| `/health` | Sin contenido sensible | Healthcheck de Docker |

## Contenido de una transacción

Cada evento usa un `audit_id` estable. El agente crea ese identificador antes de invocar Plano; el filtro registra su decisión; el proveedor, el interceptor o la extensión completan la respuesta usando el mismo valor.

| Grupo | Campos principales |
|---|---|
| Identidad | `audit_id`, `conversation_id`, cliente, origen |
| Destino | proveedor, modelo, host, ruta, endpoint |
| Contenido | prompt redactado, resultado redactado, hashes y tamaños |
| Gobierno | `allow`/`deny`, `filtered`, regla, `decision_id`, mensaje de política |
| Ejecución | HTTP, latencia, streaming, tool calls, bytes y estado terminal |
| Clasificación | tópico, confianza, etiquetas y propiedades operativas |
| Errores | tipo, mensaje y fase en que ocurrió |

El dashboard permite buscar por prompt, respuesta, regla, modelo o identificador. También filtra por tópico, proveedor, decisión, origen y ventana temporal. El panel lateral muestra el prompt y resultado completos junto con todas las características de la solicitud.

## Agrupación por tópicos

La clasificación local es determinista y no envía contenido a otro modelo. La demo reconoce `gobierno_y_politica`, `seguridad_y_datos`, `programacion`, `ciencia_y_educacion`, `finanzas`, `soporte_al_cliente`, `salud`, `redaccion_y_traduccion` y `general`. La clasificación se calcula después de la redacción y puede sustituirse por una taxonomía corporativa.

## Cuentas web gratuitas

La extensión ejecuta el siguiente ciclo en ChatGPT, Claude, Grok y Gemini:

```text
compositor web
  -> extensión extrae solo el texto editable
  -> POST /api/policy-check
  -> Plano + policy-guard
       deny  -> banner, evento blocked, no submit
       allow -> replay del click/submit original
                 -> el sitio confirma consumo del prompt
                 -> MutationObserver espera respuesta visible estable
                 -> POST /api/web-result
                 -> evento completed
```

La reparación elimina la lógica que marcaba el evento de click como usado antes de la respuesta asíncrona. La autorización queda asociada al **prompt exacto** durante una ventana breve, por lo que no autoriza otro texto. Si el sitio no confirma el envío, la extensión registra `provider_send_not_confirmed`; si no observa una respuesta, registra `provider_response_timeout`.

Ejecute la prueba controlada dentro del Chromium real del escritorio:

```bash
./scripts/test-free-web-fixture.sh
```

El resultado esperado es:

```text
PASS: prompt benigno autorizado, reenviado, respondido y auditado.
PASS: prompt adversarial bloqueado por Plano antes del submit.
Flujo free web: 2 PASS, 0 FAIL
```

## Privacidad y retención

Antes de persistir, el servicio aplica una segunda redacción a claves privadas, tokens OpenAI/Anthropic/GitHub/AWS, asignaciones comunes de secretos, correos, teléfonos y tarjetas. La demo conserva eventos durante siete días y limita el volumen predeterminado a 20 000 registros. Estos valores se configuran con `AUDIT_RETENTION_DAYS` y `AUDIT_MAX_EVENTS`.

> El dashboard contiene contenido conversacional y debe considerarse una superficie sensible. En producción requiere identidad corporativa, RBAC, cifrado en reposo, separación de funciones, retención mínima, trazabilidad de acceso y revisión legal.

La redacción por expresiones regulares reduce exposición, pero no sustituye un sistema DLP completo. Tampoco debe asumirse que cualquier contenido propietario es detectable. Para una demostración sin contenido persistido, ejecute `make purge` al finalizar.

## Verificación

```bash
./scripts/validate.sh
./scripts/smoke-test.sh
./scripts/test-free-web-fixture.sh
```

La regresión vigente verifica autenticación, resumen de allow/deny, prompt y resultado correlacionados, tópicos, redacción, prevalidación Gemini, respuesta web, streaming, TLS y ausencia de llamadas upstream ante bloqueos. Las evidencias se encuentran en `artifacts/audit-dashboard-smoke-test-final.txt`, `artifacts/free-web-fixture-test-final.txt`, `artifacts/audit-dashboard-final.png`, `artifacts/audit-dashboard-detail.png` y `artifacts/audit-dashboard-blocked-detail.png`.

## Limitaciones de las interfaces gratuitas

Las interfaces web no constituyen una API estable: el proveedor puede modificar DOM, selectores, eventos o mecanismos de sesión. La extensión intenta degradar de forma segura; si no puede encontrar el compositor o confirmar el submit, detiene el envío y registra el error. Para integraciones de producción debe preferirse la API oficial gobernada por Plano.
