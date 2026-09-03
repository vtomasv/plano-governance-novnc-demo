# Diagnóstico resuelto: dashboard y cuentas web gratuitas

**Estado:** corregido y validado el 3 de septiembre de 2026.

## Síntoma observado

En ChatGPT, Grok y otras cuentas web, la extensión mostraba que Plano estaba inspeccionando o que el prompt había sido permitido, pero el proveedor no iniciaba la conversación. Además, la arquitectura no conservaba una transacción completa con prompt, decisión y resultado.

## Causa raíz

La extensión antigua usaba listeners de captura independientes para `click`, `keydown` y `submit` junto con un bypass de un solo uso. Una aplicación web puede producir una cascada `click`→`submit`: el primer evento consumía el bypass antes de que el segundo alcanzara la aplicación. La prevalidación finalizaba correctamente, pero el submit real podía volver a ser interceptado.

También faltaban confirmación de consumo del compositor, observación de la respuesta, correlación persistente y soporte explícito para Gemini. La extracción del prompt podía ascender desde el botón hacia un contenedor demasiado amplio y capturar texto ajeno al compositor.

## Solución aplicada

| Área | Corrección |
|---|---|
| Autorización | Ventana breve vinculada al **prompt exacto** y al `audit_id` |
| Replay | Reutilización del botón/formulario original; `requestSubmit()` cuando existe |
| Prompt | Lectura exclusiva de `textarea` o `[contenteditable=true]` |
| Confirmación | Se comprueba que el compositor se vacíe o aparezca el mensaje de usuario |
| Resultado | `MutationObserver` y sondeo capturan la última respuesta visible estable |
| Errores | `provider_send_not_confirmed` y `provider_response_timeout` quedan auditados |
| Política | El parser extrae el mensaje y `decision_id` anidados en `agent_response` de Plano |
| Gemini | Dominios, extensión, escritorio `6083`, modelo, TLS, proxy y fixture añadidos |
| Auditoría | Servicio SQLite autenticado con correlación por `audit_id` |

Un `deny` muestra el mensaje de política y no ejecuta el submit. Un `allow` reenvía la acción, espera confirmación y completa el evento con la respuesta. El proxy TLS continúa siendo el enforcement de red; la extensión no lo sustituye.

## Validación

```bash
./scripts/smoke-test.sh
./scripts/test-free-web-fixture.sh
```

La suite obtuvo **34 PASS, 0 FAIL**. La prueba del Chromium real obtuvo **2 PASS, 0 FAIL**: el prompt benigno fue autorizado, reenviado, respondido y auditado; el prompt adversarial fue bloqueado antes del submit.

Las evidencias se encuentran en:

| Evidencia | Contenido |
|---|---|
| `artifacts/audit-dashboard-smoke-test-final.txt` | 34 comprobaciones end-to-end |
| `artifacts/free-web-fixture-test-final.txt` | Ciclo free-web permitido y bloqueado |
| `artifacts/audit-dashboard-detail.png` | Prompt y respuesta permitidos |
| `artifacts/audit-dashboard-blocked-detail.png` | Regla, HTTP 403 y mensaje de denegación |
| `artifacts/audit-dashboard-visual-validation.md` | Revisión visual y funcional |

## Límite conocido

Los sitios gratuitos pueden modificar su DOM y eventos sin previo aviso. La extensión falla cerrada cuando no puede identificar el compositor o confirmar el envío, y registra un error accionable en lugar de dejar al usuario esperando indefinidamente. Para producción debe preferirse una API oficial gobernada por Plano.
