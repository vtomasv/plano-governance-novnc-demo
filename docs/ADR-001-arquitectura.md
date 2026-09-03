# ADR-001 — Arquitectura de la demo de gobierno con Plano y noVNC

**Estado:** aceptada para implementación dual.

## Decisión

La demo combina dos rutas complementarias. La ruta **determinista y totalmente verificable** envía solicitudes compatibles con OpenAI, Anthropic y xAI a un listener de modelo de Plano, con proveedores locales simulados —incluido Gemini— y streaming SSE. La ruta **de cuentas web gratuitas** abre ChatGPT, Claude, Grok y Gemini en cuatro escritorios Chromium independientes expuestos por noVNC. Estos escritorios no tienen salida directa: su único camino es un proxy TLS explícito, con una CA raíz de laboratorio instalada deliberadamente en el sistema y en el almacén NSS de Chromium. El proxy consulta a Plano antes de permitir una solicitud de conversación; una extensión muestra la decisión, reenvía únicamente prompts autorizados y correlaciona la respuesta visible en el dashboard.

No se almacenarán contraseñas, cookies ni tokens en el repositorio. El usuario iniciará sesión manualmente cuando quiera probar cuentas web. Los endpoints internos de estas interfaces web se consideran privados y cambiantes; por ello la validación automática no dependerá de ellos. Plano seguirá siendo el **único punto de decisión**: si Plano o su filtro no están disponibles, el proxy fallará cerrado para solicitudes de conversación.

## Comparación de enfoques

| Enfoque | Compromisos | Coste | Complejidad de configuración |
|---|---|---:|---:|
| Escritorios noVNC con cuentas web gratuitas, proxy TLS y consulta obligatoria a Plano | Cumple la experiencia visual y no requiere API keys, pero los endpoints privados de las interfaces pueden cambiar y la prueba completa exige login manual. El proxy preserva el tráfico web; la decisión se externaliza a Plano. | Sin coste de API; sujeto a los términos y límites de cada servicio | Alta |
| Clientes API compatibles con OpenAI/Anthropic/xAI a través del listener nativo de Plano | Es la ruta más estable, observable y fiel al dataplane; requiere API keys para proveedores reales. Sin claves se prueba con proveedores locales simulados. | Cero en modo local; variable con APIs reales | Media |
| Automatización por scraping o reutilización de cookies privadas | Frágil, insegura, difícil de reproducir y potencialmente incompatible con términos del proveedor. | Impredecible | Muy alta |

La demo implementará los dos primeros enfoques y excluirá explícitamente el tercero.

## Flujo de control

```text
Navegador del operador
        |
        +--> noVNC :6080/:6081/:6082/:6083
                  |
       +--------+--------+--------+
       |        |        |        |
 Chromium Chromium Chromium Chromium
 ChatGPT   Claude    Grok    Gemini
       \        |        |       /
        \       red interna      /
         +-- sin egress ---+
                 |
        proxy-interceptor TLS
        (CA explícitamente confiada)
                 |
      solicitud de decisión normalizada
                 v
      Plano :12000 (model listener)
                 |
       input_filter: policy-guard
          | bloquea      | permite
          v              v
      HTTP 403     policy-provider local
          |              |
          +------ decisión al proxy
                         |
                upstream web real

Ruta API verificable:
cliente de pruebas --> Plano :12000 --> policy-guard --> proveedor local/real
```

## Política principal

El filtro inspeccionará el historial completo de roles de usuario y los campos de entrada compatibles con `/v1/chat/completions`, `/v1/responses` y `/v1/messages`. Bloqueará preguntas sobre el presidente de Argentina, incluyendo menciones o errores tipográficos cercanos a `Milei`, como `Miley` y `Mliey`, cuando aparezcan con términos presidenciales o con contexto argentino. La respuesta estable será:

> No es posible realizar preguntas sobre el presidente de Argentina.

La política incluirá además detecciones mínimas de secretos para demostrar prevención de pérdida de datos. Los logs operativos no conservan el cuerpo completo del prompt; registran identificador, proveedor, regla, decisión y huellas criptográficas. El dashboard persiste una copia **redactada** del prompt y resultado durante una retención limitada, detrás de autenticación, para la finalidad explícita de esta demo de auditoría.

## Límites

La intercepción TLS está restringida a la red Docker de laboratorio y solo funciona porque cada cliente confía explícitamente en la CA generada. No se instalará la CA en el host. En producción se deben usar certificados y gestión de claves corporativos, control de acceso, rotación, auditoría, límites de retención y revisión legal. La demo no intenta romper certificate pinning, evadir controles del proveedor ni reutilizar credenciales fuera de la sesión del usuario.

## Dependencias fijadas

| Componente | Versión/base |
|---|---|
| Plano | `katanemo/plano` commit `003c36aea896ce6fa98567329588baa582e41f9c` (0.4.36) |
| noVNC | `v1.7.0` |
| mitmproxy | Se fijará por digest o versión explícita en la imagen de la demo |
| Chromium/Xfce/x11vnc | Paquetes del sistema fijados por la imagen base de Ubuntu seleccionada |

## Referencias

[1]: https://github.com/katanemo/plano "Plano — repositorio oficial"
[2]: https://docs.planoai.dev/concepts/filter_chain.html "Plano — Filter Chains"
[3]: https://github.com/novnc/noVNC/releases/tag/v1.7.0 "noVNC 1.7.0"
[4]: https://novnc.com/noVNC/docs/EMBEDDING.html "Embedding and deploying noVNC"
