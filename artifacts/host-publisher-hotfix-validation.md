# Validación del hotfix de `host-publisher`

**Fecha:** 3 de septiembre de 2026
**Resultado:** aprobado

## Fallo reproducido

Una reproducción mínima con `depends_on: condition: service_healthy` y un backend no saludable produjo este estado:

```text
up_rc=1
dependency failed to start: container ... is unhealthy
publisher   Created
unhealthy-backend   Up (unhealthy)
```

Docker creó el contenedor publisher, pero no lo inició. En Docker Desktop este comportamiento se percibe como publisher ausente o sin interfaces utilizables.

## Corrección

`host-publisher` ya no depende del estado de salud de los backends. HAProxy puede iniciar sin ellos porque su configuración usa resolución DNS dinámica, `init-addr last,libc,none` y healthchecks propios. Los backends pasan a estado UP cuando estén disponibles.

`scripts/mac-up.sh` ahora ejecuta esta secuencia antes del arranque general:

```text
1. Renderiza el Compose y exige el servicio host-publisher.
2. Crea host-publisher explícitamente.
3. Verifica sus 18 PortBindings en HostConfig.
4. Lo inicia y exige estado running.
5. Solo entonces inicia o construye el resto de la pila.
```

## Prueba positiva aislada

El publisher final se creó e inició sin que existiera ningún backend:

```text
created_status=created bindings_count=18
running_status=running health=starting
stats_http=200
runtime_publisher_hotfix=PASS
```

El endpoint de estadísticas respondió HTTP 200. La validación estática también prohíbe reintroducir cualquier `depends_on` en `host-publisher`.
