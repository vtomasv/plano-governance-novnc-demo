# Diagnóstico de puertos y superficies operativas

## Síntomas reproducidos

El archivo principal `docker-compose.yml` sí publica `6080`, `6081` y `6082`, además de `10500`, `10501`, `10600`, `12000`, `16686`, `19901` y `8081` en `127.0.0.1`.

El síntoma descrito —Plano visible en `12000/8001/19901`, mitmweb visible en `8081`, pero escritorios y otros servicios sin puertos publicados— aparece al combinar el Compose principal con `dev/docker-compose.sandbox-internal.yml`. Ese override contiene `network_mode: host` y `ports: !reset []` para todos los servicios. En Linux con red de host los procesos siguen escuchando directamente en el host, pero Docker no muestra mapeos en la columna `PORTS`; en Docker Desktop, la semántica puede ser distinta o no estar habilitada.

## Causa raíz

Docker había creado la mayoría de los contenedores con `HostConfig.PortBindings={}`. Un contenedor conserva esa configuración cuando se pulsa **Start**; los bindings solo aparecen al recrearlo con una configuración que contenga `ports`.

Se reprodujo el mismo patrón mediante un `COMPOSE_FILE` externo que fusionó un override y eliminó los puertos. Otros desencadenantes equivalentes son `docker compose run`, el botón **Run** sobre una imagen o una pila obsoleta. `dev/docker-compose.sandbox-internal.yml` sigue siendo un workaround exclusivo del sandbox y no es un archivo de despliegue.

## Correcciones aplicadas

1. El despliegue soportado usa `scripts/up.sh` o `scripts/up.ps1`; ambos fuerzan el Compose principal y tienen mapeos explícitos y configurables.
2. El override interno se movió a `dev/` y está marcado como no soportado para Docker Desktop.
3. Se añadió Control Center en `http://127.0.0.1:10000` con salud, enlaces y configuración operativa segura.
4. La contraseña de mitmweb es `MITMWEB_PASSWORD`, independiente de `VNC_PASSWORD`, y se muestra al finalizar el arranque.
5. Plano tiene healthcheck contra `/healthz`; Envoy Admin en `19901` queda documentado como diagnóstico, no como editor de configuración.
6. Los wrappers fuerzan la ruta absoluta del Compose principal, ignoran `COMPOSE_FILE` y fijan el nombre de proyecto.
7. El arranque usa `--force-recreate` y valida `HostConfig.PortBindings` antes de informar éxito.
8. Docker Desktop dispone de scripts PowerShell nativos para iniciar, detener y diagnosticar.
