# Diagnóstico de puertos y superficies operativas

## Síntoma histórico

La primera versión publicaba puertos desde cada servicio. Algunos despliegues quedaron con `HostConfig.PortBindings={}` en los escritorios, mientras Plano conservaba bindings. Un contenedor no adquiere puertos al pulsar **Start**: solo al recrearse con una configuración que declare `ports`.

El patrón se reprodujo mediante un `COMPOSE_FILE` externo y también puede aparecer al usar `docker compose run`, el botón **Run** sobre una imagen o el override interno de desarrollo.

## Estrategia actual en Mac

El perfil macOS ya no publica cada servicio de forma independiente. `mac-up.sh` combina:

```text
docker-compose.yml
docker-compose.mac-arm64.yml
docker-compose.mac-publisher.yml
```

`host-publisher-1` ejecuta HAProxy y es el **único contenedor con PortBindings**. Los tres escritorios, Plano, Policy Guard, Governed Agent, Jaeger, mitmweb y proveedores aparecen sin puertos en Docker Desktop por diseño.

| Estado en Docker Desktop | Interpretación |
|---|---|
| `host-publisher-1` muestra `6080`, `6081`, `6082`, etc. | Correcto |
| Los escritorios no muestran `Port(s)` | Correcto; HAProxy los publica |
| `host-publisher-1` tampoco muestra puertos | Fallo; recrear la pila |
| `http://127.0.0.1:8404` muestra backends UP | Publisher operativo |

## Verificación

```bash
./scripts/check-publisher-ports.sh
./scripts/mac-diagnose.sh
```

El resultado esperado es:

```text
host-publisher: 16 bindings en 127.0.0.1
servicios internos: 11 sin bindings directos
publisher sin red egress
13 imágenes linux/arm64
```

## Recuperación

```bash
git pull
chmod +x scripts/*.sh
./scripts/down.sh
./scripts/mac-up.sh
```

No agregue `-f dev/docker-compose.sandbox-internal.yml`, no use `docker compose run` y no cree los escritorios desde el botón **Run** de una imagen.

## Controles aplicados

1. HAProxy 3.2.22 se fija por digest arm64 y usa configuración de solo lectura.
2. Todos los bindings están hardcodeados a `127.0.0.1`.
3. Los escritorios pertenecen solo a la red `control`.
4. `host-publisher` no pertenece a la red `egress`.
5. El arranque falla si falta un binding o aparece uno directo en un backend.
6. Control Center expone la salud consolidada en `10000`; HAProxy expone estadísticas en `8404`.
7. El modo TCP conserva WebSocket/noVNC, TLS, SSE y gRPC sin terminación ni reescritura.
