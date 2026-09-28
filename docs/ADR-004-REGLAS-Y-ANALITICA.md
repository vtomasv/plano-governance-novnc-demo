# ADR-004: gestión de reglas en caliente y analítica de uso con Ollama

## Estado

**Aceptado** para la demo.

## Contexto

Las reglas de gobierno estaban fijas en `policy-guard/app.py`: cambiarlas exigía editar código y recrear el contenedor. Tampoco había forma de saber **para qué** se usa la IA, más allá de un clasificador de tópicos por palabras clave.

## Decisión 1: reglas declarativas con recarga inmediata

```text
Dashboard /rules ──PUT/POST──> audit-dashboard (SQLite: policy_rules + historial)
                                   │ 1. valida el borrador con policy-guard (/admin/test)
                                   │ 2. guarda y sube la revisión global
                                   │ 3. POST /admin/reload  (aplicación inmediata)
                                   v
                              policy-guard  ◄── sondeo GET /policy/rules cada 5 s (respaldo)
```

- **Fuente de verdad:** el dashboard. Las reglas de fábrica viven en `policy-guard/default_rules.py` y siembran la base una sola vez; borrar todas las reglas no las restaura.
- **Modelo:** una regla se dispara si **alguna cláusula** (O) se cumple; una cláusula se cumple si **todos sus grupos** (Y) coinciden; un grupo coincide si aparece **algún** término exacto (normalizado: acentos, mayúsculas, leetspeak), término difuso (una edición o transposición) o regex. Modos: `enforce` (403) y `monitor` (permite y registra en `properties.monitor_rules`).
- **Quien ejecuta valida:** el guard decide si una regla compila; el dashboard le delega la validación. Una regla inválida nunca se guarda. Si una llega inválida al guard, se omite y las demás siguen activas.
- **Sin cortes:** el conjunto de reglas se reemplaza de forma atómica. Si el dashboard cae, el guard conserva la última revisión válida (o las reglas de fábrica si nunca se conectó).
- **Auditoría:** cada cambio queda en `policy_rule_history` (versión, autor, foto completa) y permite restaurar una versión anterior.
- **Regex:** se rechazan cuantificadores anidados (`(a+)+`) para reducir el riesgo de ReDoS; no es una garantía completa.

> Los handlers del dashboard que llaman al guard **deben** ejecutarse en un threadpool: el guard, al recargar, vuelve a llamar al dashboard, y bloquear el event loop provoca un timeout de 3 s.

## Decisión 2: analítica de uso al estilo Anthropic Economic Index

Un worker del dashboard envía cada prompt **ya redactado** a un modelo local en Ollama (`qwen2.5:7b-instruct`, temperatura 0, salida restringida por JSON Schema) y guarda en `event_analysis`:

| Campo | Valores |
|---|---|
| `task_category` | 16 tareas (desarrollo de software, redacción, análisis de datos, legal…) |
| `occupation_group` | 13 grupos ocupacionales condensados |
| `interaction_pattern` | `directiva`, `ciclo_de_retroalimentacion` (**automatización**); `aprendizaje`, `iteracion`, `validacion` (**aumentación**); `sin_tarea` |
| `usage_context` | trabajo, educación, personal, no claro |
| `task_summary` | frase genérica de la tarea, sin datos personales |

`/usage` muestra el reparto automatización/aumentación, tareas, patrones, un **explorador por ocupación** (equivalente al Job Explorer), evolución diaria y proveedor. Es una inferencia del modelo, no una medición exacta; el prompt incluye reglas y ejemplos para reducir el sesgo hacia `validacion`.

## Red: cómo llega el contenedor al Ollama del Mac

Ollama corre **nativo** para usar la GPU Metal. Los contenedores no tienen salida a Internet, así que `host-publisher` (HAProxy) actúa de puente:

```text
audit-dashboard ──red "analytics" (interna, 172.31.240.0/28)──> host-publisher:11434 ──> host.docker.internal:11434
```

- El puerto 11434 **no se publica** en el host: los 18 bindings de `host-publisher` no cambian.
- HAProxy rechaza (`tcp-request connection reject`) cualquier origen fuera de la subred `analytics`, de modo que los escritorios (red `control`) no pueden usar Ollama.
- Ollama sigue escuchando solo en `127.0.0.1`.

## Consecuencias

- Si Ollama no está disponible, la auditoría y las reglas siguen funcionando; los prompts quedan en cola y `/usage` lo indica.
- En Linux (`docker-compose.yml` sin el perfil Mac) no existe `host-publisher`; defina `OLLAMA_URL` con una dirección alcanzable.
- El contenido de los prompts se almacena en SQLite y se analiza localmente: aplican las mismas advertencias de sensibilidad de ADR-003.
