# Informe de validación de la demo

**Fecha:** 27 de agosto de 2026  
**Resultado general:** aprobado

| Área | Resultado | Evidencia |
|---|---:|---|
| Tests unitarios del filtro | 10/10 PASS | `python3 -m pytest -q policy-guard/test_policy.py` |
| Suite end-to-end | 16/16 PASS | `artifacts/smoke-test-final.txt` |
| ChatGPT local gobernado | PASS | Respuesta permitida y routing a `custom/local-chatgpt` |
| Claude local gobernado | PASS | Respuesta permitida y routing a `custom/local-claude` |
| Grok local gobernado | PASS | Respuesta permitida y routing a `custom/local-grok` |
| Bloqueo Milei/Miley/Mliey | PASS | HTTP 403, texto estable y cero llamadas upstream |
| Contexto multivuelta | PASS | Se bloqueó al combinar `Argentina` y `presidente` entre turnos |
| Prevención de fuga | PASS | Se bloqueó un patrón `api_key=...` |
| Streaming | PASS | Chunks SSE y `[DONE]` preservados |
| MITM TLS controlado | PASS | Solicitud permitida y denegada a `chatgpt.demo.local` mediante CA confiada |
| Confianza del cliente | PASS | CA presente en trust store del sistema y NSS/Chromium |
| Observabilidad | PASS | Jaeger registró `plano(filter)`, `plano(llm)`, `plano(outbound)` y `plano(routing)` |
| noVNC | PASS | Puertos 6080, 6081 y 6082 saludables |
| UI de bloqueo | PASS | `artifacts/ui-blocked-final.png` muestra el mensaje exacto |

## Estado operativo

La pila permanece levantada en este sandbox mediante `docker-compose.sandbox.yml`, necesario porque el kernel de ejecución no soporta bridge/netfilter anidado. Todos los servicios de larga duración están en estado `Up`; `cert-init` terminó correctamente con código 0.

El despliegue recomendado para un host Docker normal usa únicamente `docker-compose.yml`, que conserva las redes internas `control` y `upstream-sim` y la red `egress` restringida al proxy y a Plano.

## Capturas principales

- `artifacts/desktop-clean-final.png`: escritorio noVNC con la interfaz ChatGPT gobernada.
- `artifacts/ui-blocked-final.png`: prompt `¿Mliey es el presidente de Argentina?` bloqueado por Plano.
- `artifacts/runtime-evidence.txt`: CA, decisiones anonimizadas, servicios Jaeger y estado de contenedores.
