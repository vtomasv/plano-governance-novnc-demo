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
| Compose | Combina solo `docker-compose.yml` y `docker-compose.mac-arm64.yml` |
| Estado anterior | Elimina contenedores obsoletos del mismo proyecto |
| Puertos ocupados | Los detecta con `lsof` antes de construir |
| Imágenes | Comprueba que cada imagen sea arm64 |
| Bindings | Comprueba directamente `HostConfig.PortBindings` |
| Interfaces | Espera Control Center, Plano Admin y los tres noVNC |

La primera compilación del escritorio Xfce/Chromium descarga numerosos paquetes; las siguientes reutilizan la caché de Docker.

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

Las contraseñas predeterminadas de noVNC y mitmweb son `plano-demo`; se cambian en `.env` mediante `VNC_PASSWORD` y `MITMWEB_PASSWORD`.

## 4. Diagnóstico

```bash
./scripts/mac-diagnose.sh
./scripts/smoke-test.sh
```

El diagnóstico debe mostrar **15 bindings** y todas las imágenes como `linux/arm64`. La suite funcional debe terminar en `Resultado: 23 PASS, 0 FAIL`.

Para guardar un diagnóstico compartible:

```bash
./scripts/mac-diagnose.sh 2>&1 | tee mac-diagnose.txt
./scripts/compose.sh ps -a | tee -a mac-diagnose.txt
```

El archivo no contiene tokens ni cuerpos de prompts, pero conviene revisarlo antes de compartirlo.

## 5. Recuperación

Si Docker Desktop todavía muestra contenedores sin puertos:

```bash
./scripts/down.sh
./scripts/mac-up.sh
```

Si el arranque informa que un puerto está ocupado, identifique el proceso y cambie el puerto correspondiente en `.env`:

```bash
lsof -nP -iTCP:6080 -sTCP:LISTEN
lsof -nP -iTCP:6081 -sTCP:LISTEN
lsof -nP -iTCP:6082 -sTCP:LISTEN
```

No cambie los puertos internos de los contenedores; modifique únicamente los valores del host, por ejemplo `CHATGPT_NOVNC_PORT=16080`.

## 6. Evidencia de compatibilidad

La versión publicada fue construida para `linux/arm64` bajo emulación QEMU en un host de validación amd64. Se verificaron doce imágenes arm64, quince bindings, Chromium/noVNC, Plano, mitmweb, TLS interceptado, streaming y las veintitrés pruebas funcionales. Los resultados están en `artifacts/mac-arm64-validation.txt` y `artifacts/mac-arm64-smoke-test.txt`.

## Referencias

[1]: https://docs.docker.com/desktop/setup/install/mac-install/ "Install Docker Desktop on Mac"
[2]: https://docs.docker.com/build/building/multi-platform/ "Multi-platform builds"
[3]: https://docs.docker.com/engine/network/port-publishing/ "Port publishing and mapping"
