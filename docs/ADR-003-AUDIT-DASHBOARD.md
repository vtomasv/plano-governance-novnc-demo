# ADR-003: auditoría local de solicitudes LLM

## Estado

**Aceptado** para la demo. El almacenamiento de contenido debe tratarse como sensible.

## Objetivo

Registrar una vista correlacionada de cada solicitud gobernada: quién la originó, qué proveedor/modelo seleccionó, qué prompt se evaluó, qué política se aplicó, si el flujo fue permitido o bloqueado y cuál fue la respuesta final.

## Arquitectura

```text
Extensión / agente / proxy / filtro / provider-sim
                     |
              x-audit-token
                     v
          audit-dashboard :10700
            SQLite /data/audit.db
                     |
       UI, filtros, tópicos, detalle, CSV/JSON
```

El servicio está solo en la red `control`, no posee egress y persiste en un volumen Docker. En Mac se publica exclusivamente mediante `host-publisher` sobre `127.0.0.1:10700`.

## Identidad y correlación

Cada transacción usa un UUID `audit_id`. El agente o interceptor lo crea antes de consultar Plano y lo envía dentro de `metadata.audit_id`. `policy-guard` hace upsert de la decisión sobre ese ID; `provider-sim`, el agente o el interceptor completan resultado, latencia y estado. `decision_id` de Plano permanece como campo separado.

## Esquema lógico

| Campo | Propósito |
|---|---|
| `audit_id` | Correlación estable de extremo a extremo |
| `conversation_id` | Agrupación multivuelta cuando el cliente la proporciona |
| `started_at`, `completed_at`, `duration_ms` | Línea temporal y latencia |
| `source`, `client`, `provider`, `model` | Origen y destino lógico |
| `target_host`, `target_path`, `endpoint` | Ruta de red sin query ni credenciales |
| `topic`, `topic_confidence`, `tags` | Agrupación determinista |
| `prompt_text`, `prompt_sha256`, `prompt_chars` | Prompt redactado, integridad y tamaño |
| `response_text`, `response_chars` | Resultado redactado |
| `decision`, `filtered`, `rule`, `decision_id` | Gobierno aplicado |
| `policy_message`, `redaction_count` | Explicación de la política |
| `status_code`, `streaming`, `tool_calls` | Características técnicas |
| `request_bytes`, `response_bytes` | Tamaño aproximado |
| `state`, `error_type`, `error_message` | `pending`, `completed`, `blocked` o `error` |

## Tópicos

La clasificación es local y determinista; no genera una segunda llamada LLM. Las categorías iniciales son `gobierno_y_politica`, `seguridad_y_datos`, `programacion`, `ciencia_y_educacion`, `finanzas`, `soporte_al_cliente`, `salud`, `redaccion_y_traduccion` y `general`. El dashboard permite filtrar y agrupar por tópico, proveedor, decisión, fuente y ventana temporal.

## Privacidad y seguridad

Antes de persistir, el servicio vuelve a redactar claves privadas, API keys, tokens GitHub/AWS, bearer tokens, cookies y valores de campos sensibles. Nunca recibe cabeceras `Authorization`, cookies ni el cuerpo HTTP bruto. Prompt y respuesta se guardan solo porque el usuario solicitó inspección detallada; la retención predeterminada es siete días y diez mil eventos.

La API de lectura usa autenticación Basic (`admin` y `AUDIT_DASHBOARD_PASSWORD`). La ingesta usa `x-audit-token` con `AUDIT_INGEST_TOKEN`. `/health` no requiere autenticación. El puerto está limitado a loopback.

> En producción, el almacenamiento de prompts y respuestas requiere base legal, controles de acceso, cifrado administrado, segregación por tenant, retención aprobada, auditoría inmutable y un proceso formal de borrado. SQLite y credenciales demo no satisfacen esos requisitos.
