# Ejecución en macOS Apple Silicon (M1/M2/M3/M4)

Esta es la ruta soportada para un **Mac M3**. Docker Desktop para Apple Silicon ejecuta una VM Linux arm64; por ello la demo construye y ejecuta variantes `linux/arm64` nativas, sin depender de imágenes Intel ni de Rosetta para los contenedores.[1][2]

## 1. Preflight

Abra Terminal en la raíz del repositorio y confirme:

```bash
uname -m
docker context show
docker version --format 'client={{.Client.Arch}} server={{.Server.Arch}}/{{.Server.Os}}'
docker compose version
```

El resultado requerido es `arm64` para el Mac y `arm64/linux` para Docker Server. Si Docker Server informa `amd64`, instale o seleccione **Docker Desktop for Mac with Apple silicon**.[1]

La demo expone las interfaces solo en `127.0.0.1`. Docker documenta que un puerto publicado sobre loopback queda accesible únicamente desde el host, que es el comportamiento buscado para este laboratorio.[3]

## 2. Actualización y arranque limpio

```bash
git pull
chmod +x scripts/*.sh
./scripts/down.sh
./scripts/mac-up.sh
```

`mac-up.sh` realiza automáticamente estas operaciones:

| Control | Comportamiento |
|---|---|
| Plataforma | Fuerza `linux/arm64` |
| Compose | Combina `docker-compose.yml`, `docker-compose.mac-arm64.yml` y `docker-compose.mac-publisher.yml` |
| Estado anterior | Elimina contenedores obsoletos del mismo proyecto |
| Puertos ocupados | Los detecta con `lsof` antes de construir |
| Imágenes | Comprueba trece imágenes arm64, incluido HAProxy |
| Bindings | Exige dieciséis bindings únicamente en `host-publisher` y ninguno en los servicios internos |
| Interfaces | Espera Control Center, Plano Admin y los tres noVNC |

La primera compilación del escritorio Xfce/Chromium descarga numerosos paquetes; las siguientes reutilizan la caché de Docker.

### Qué debe mostrar Docker Desktop

En la columna **Port(s)**, `desktop-chatgpt`, `desktop-claude`, `desktop-grok`, Plano y los demás servicios internos deben aparecer **sin puertos**. Esto ya no indica un fallo: todos los bindings estarán concentrados en `host-publisher-1`. Allí deben verse `6080`, `6081`, `6082`, `10000`, `12000`, `19901`, `8081`, `16686` y los demás puertos operativos.

HAProxy trabaja en modo TCP, por lo que no termina TLS ni modifica HTTP, SSE, gRPC o WebSocket. El publisher no pertenece a la red `egress`; solo puede alcanzar backends explícitos de `control` y `upstream-sim` mediante su configuración.[4][5]

> No use el botón **Run** de una imagen ni `docker compose run`. Tampoco combine manualmente el archivo de `dev/`, ya que ese override elimina deliberadamente los bindings para un sandbox Linux restringido.

## 3. Accesos

| Interfaz | URL |
|---|---|
| Control Center | `http://127.0.0.1:10000/` |
| ChatGPT noVNC | `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=remote` |
| Claude noVNC | `http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=remote` |
| Grok noVNC | `http://127.0.0.1:6082/vnc.html?autoconnect=1&resize=remote` |
| Plano Gateway | `http://127.0.0.1:12000/` |
| Plano/Envoy Admin | `http://127.0.0.1:19901/` |
| mitmweb | `http://127.0.0.1:8081/` |
| Jaeger | `http://127.0.0.1:16686/` |
| HAProxy stats | `http://127.0.0.1:8404/` |

Las contraseñas predeterminadas de noVNC y mitmweb son `plano-demo`; se cambian en `.env` mediante `VNC_PASSWORD` y `MITMWEB_PASSWORD`.

## 4. Diagnóstico

```bash
./scripts/mac-diagnose.sh
./scripts/smoke-test.sh
```

El diagnóstico debe mostrar **16 bindings en `host-publisher`**, **cero bindings directos en once servicios internos** y trece imágenes `linux/arm64`. La suite funcional debe terminar en `Resultado: 23 PASS, 0 FAIL`.

Para guardar un diagnóstico compartible:

```bash
./scripts/mac-diagnose.sh 2>&1 | tee mac-diagnose.txt
./scripts/compose.sh ps -a | tee -a mac-diagnose.txt
```

El archivo no contiene tokens ni cuerpos de prompts, pero conviene revisarlo antes de compartirlo.

## 5. Recuperación

Si Docker Desktop muestra los escritorios sin puertos, primero compruebe `host-publisher-1`: ese es el estado esperado. Si `host-publisher-1` tampoco muestra bindings, recréelo:

```bash
./scripts/down.sh
./scripts/mac-up.sh
./scripts/check-publisher-ports.sh
```

Si el arranque informa que un puerto está ocupado, identifique el proceso y cambie el puerto correspondiente en `.env`:

```bash
lsof -nP -iTCP:6080 -sTCP:LISTEN
lsof -nP -iTCP:6081 -sTCP:LISTEN
lsof -nP -iTCP:6082 -sTCP:LISTEN
```

No cambie los puertos internos de los contenedores; modifique únicamente los valores del host, por ejemplo `CHATGPT_NOVNC_PORT=16080`.

## 6. Evidencia de compatibilidad

La versión publicada fue construida para `linux/arm64` bajo emulación QEMU en un host de validación amd64. Se verificaron trece imágenes arm64 y dieciséis bindings concentrados en HAProxy. En una ejecución funcional equivalente se comprobaron las 23 políticas, el upgrade WebSocket `101`, una sesión noVNC visual, streaming SSE, TLS interceptado y mitmweb. Los resultados están en `artifacts/mac-publisher-validation.txt`, `artifacts/host-publisher-smoke-test.txt` y `artifacts/host-publisher-visual-validation.md`.

## Referencias

[1]: https://docs.docker.com/desktop/setup/install/mac-install/ "Install Docker Desktop on Mac"
[2]: https://docs.docker.com/build/building/multi-platform/ "Multi-platform builds"
[3]: https://docs.docker.com/engine/network/port-publishing/ "Port publishing and mapping"
[4]: https://www.haproxy.com/documentation/haproxy-configuration-tutorials/proxying-essentials/dns-resolution/ "HAProxy — DNS resolution"
[5]: https://docs.haproxy.org/3.2/configuration.html "HAProxy 3.2 Configuration Manual"
