# ADR-002: publisher único HAProxy para Docker Desktop en Mac

## Estado

**Aceptado** para el perfil macOS Apple Silicon.

## Contexto

La publicación directa de cada contenedor producía una experiencia ambigua en Docker Desktop: los escritorios podían aparecer sin `Port(s)` o los bindings podían depender de la combinación Compose efectiva. La estrategia propuesta concentra todos los puertos del host en un contenedor frontal y conserva los backends en redes internas.

## Decisión

Se incorpora `docker-compose.mac-publisher.yml` al flujo automático de `mac-up.sh`. `host-publisher` es el único servicio con `ports`; HAProxy reenvía en modo TCP a los backends internos. El modo TCP no termina TLS ni interpreta HTTP y, por tanto, preserva WebSocket/noVNC, SSE, gRPC y TLS passthrough.[1]

HAProxy resuelve los nombres de servicio mediante el DNS embebido de Docker. La configuración usa `resolvers`, `init-addr last,libc,none` y healthchecks TCP para tolerar recreaciones de contenedores.[2]

| Propiedad | Decisión |
|---|---|
| Bindings | Dieciséis, todos en `host-publisher` |
| Dirección | `127.0.0.1` hardcodeada en Compose |
| Escritorios | Sin bindings; solo red `control` |
| Publisher | `control`, `upstream-sim`, `publish`; nunca `egress` |
| Imagen | HAProxy 3.2.22 arm64 fijado por digest |
| Privilegios | Usuario `haproxy`, `cap_drop: ALL`, `no-new-privileges`, root filesystem de solo lectura |
| Diagnóstico | Control Center `10000`, HAProxy stats `8404`, `check-publisher-ports.sh` |

## Ajustes sobre la propuesta recibida

La idea se conserva, pero la configuración inline se movió a `host-publisher/haproxy.cfg` para facilitar linting, revisión y pruebas. Se añadió un manifest arm64 fijado, validación automática de dieciséis bindings, comprobación de que once servicios no publiquen directamente y una regla estática que falla si HAProxy se conecta a `egress`.

`BIND_ADDRESS` no controla el publisher en Mac: cada mapping usa explícitamente `127.0.0.1`. Este comportamiento fail-safe evita una exposición accidental a la LAN.

## Consecuencias

En Docker Desktop, **solo `host-publisher-1` mostrará puertos**. Los escritorios y servicios internos sin `Port(s)` constituyen el estado esperado. Si HAProxy se detiene, todas las interfaces del host dejan de estar disponibles simultáneamente, pero el dataplane interno continúa aislado.

La red `publish` no es la red de egress de la arquitectura. Sin embargo, como cualquier componente conectado a una red Docker no interna, HAProxy debe considerarse parte del perímetro: su imagen está fijada, su configuración es de solo lectura, no recibe el socket Docker y no forma parte del camino de salida de los escritorios hacia proveedores. Los escritorios siguen usando exclusivamente `proxy-interceptor:8080`; Plano conserva la decisión allow/deny.

## Validación

Se verificaron trece imágenes arm64, dieciséis bindings en HAProxy, once servicios con `PortBindings={}`, WebSocket `101`, una sesión noVNC visual y 23/23 pruebas de política, streaming y TLS. El sandbox no permite bridges Docker normales, por lo que la validación funcional usó una topología de host equivalente; la validación declarativa y de `HostConfig.PortBindings` sí utilizó el Compose Mac exacto.

## Referencias

[1]: https://docs.haproxy.org/3.2/configuration.html "HAProxy 3.2 Configuration Manual"
[2]: https://www.haproxy.com/documentation/haproxy-configuration-tutorials/proxying-essentials/dns-resolution/ "HAProxy — DNS resolution"
