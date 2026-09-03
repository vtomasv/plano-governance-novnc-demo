# Validación visual del dashboard de auditoría

Fecha de ejecución: 2026-09-03.

La captura `audit-dashboard-final.png` confirma que la interfaz carga sin errores y presenta métricas agregadas, tasa filtrada, latencia media, agrupación por tópicos, actividad temporal y tabla de solicitudes. En la ejecución observada mostró 15 solicitudes, 9 permitidas y 6 bloqueadas, con una tasa filtrada de 40 %.

La tabla distingue cliente, origen, proveedor, modelo, tópico, prompt, decisión y latencia. Los eventos del fixture de cuenta web Gemini aparecen como `gemini-free-web`, con decisión `Permitido`, tópico `Ciencia y educación`, prompt exacto y latencia de extremo a extremo. Las solicitudes adversariales aparecen como `Bloqueado` y los secretos se presentan como `[REDACTED_BY_AUDIT]`.

El API de detalle fue validado para devolver el prompt y la respuesta completos correlacionados mediante `audit_id`; la interfaz abre ese contenido en un panel lateral al seleccionar una fila. La autenticación Basic es obligatoria para la interfaz y las consultas, mientras `/health` permanece disponible para sondas.

La primera captura reveló un error al construir `fetch()` desde una URL con credenciales embebidas. El cliente fue corregido para construir URL absolutas sin `username` ni `password`; la captura final confirma la actualización automática cada cinco segundos.

## Panel de detalle

La captura `audit-dashboard-detail.png` confirma que el panel lateral presenta en una sola vista el estado permitido/bloqueado, cliente, origen, proveedor, modelo, tópico, regla, `decision_id`, HTTP, streaming, tool calls, duración, tamaños, prompt completo, resultado completo y metadata estructurada. El ejemplo validado corresponde a una solicitud real del fixture `gemini-free-web` que fue autorizada, reenviada y completada.

## Flujo web gratuito

La prueba `scripts/test-free-web-fixture.sh` ejecutó dos escenarios en el Chromium real del escritorio con la extensión cargada: un prompt benigno terminó en `completed` con respuesta DOM correlacionada y un prompt sobre «Mliey» terminó en `blocked` antes del submit. El evento final conserva el mensaje humano `No es posible realizar preguntas sobre el presidente de Argentina.` y el `decision_id` emitido por la política.

Se descartaron capturas de framebuffer que mostraban una ventana distinta del escritorio debido al gestor de ventanas de Xfce; la evidencia funcional autoritativa es el evento correlacionado del dashboard y los resultados de la prueba automatizada.
