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
| Imágenes | Comprueba quince imágenes arm64, incluido HAProxy |
| Bindings | Exige dieciocho bindings únicamente en `host-publisher` y ninguno en los servicios internos |
| Interfaces | Espera Control Center, dashboard de auditoría, Plano Admin y los cuatro noVNC |

La primera compilación del escritorio Xfce/Chromium descarga numerosos paquetes; las siguientes reutilizan la caché de Docker.

### Qué debe mostrar Docker Desktop

En la columna **Port(s)**, `desktop-chatgpt`, `desktop-claude`, `desktop-grok`, `desktop-gemini`, Plano y los demás servicios internos deben aparecer **sin puertos**. Esto ya no indica un fallo: todos los bindings estarán concentrados en `host-publisher-1`. Allí deben verse `6080`, `6081`, `6082`, `6083`, `10000`, `10700`, `12000`, `19901`, `8081`, `16686` y los demás puertos operativos.

HAProxy trabaja en modo TCP, por lo que no termina TLS ni modifica HTTP, SSE, gRPC o WebSocket. El publisher no pertenece a la red `egress`; solo puede alcanzar backends explícitos de `control` y `upstream-sim` mediante su configuración.[4][5]

> No use el botón **Run** de una imagen ni `docker compose run`. Tampoco combine manualmente el archivo de `dev/`, ya que ese override elimina deliberadamente los bindings para un sandbox Linux restringido.

## 3. Accesos

| Interfaz | URL |
|---|---|
| Control Center | `http://127.0.0.1:10000/` |
| ChatGPT noVNC | `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=remote` |
| Claude noVNC | `http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=remote` |
| Grok noVNC | `http://127.0.0.1:6082/vnc.html?autoconnect=1&resize=remote` |
| Gemini noVNC | `http://127.0.0.1:6083/vnc.html?autoconnect=1&resize=remote` |
| Dashboard de auditoría | `http://127.0.0.1:10700/` |
| Plano Gateway | `http://127.0.0.1:12000/` |
| Plano/Envoy Admin | `http://127.0.0.1:19901/` |
| mitmweb | `http://127.0.0.1:8081/` |
| Jaeger | `http://127.0.0.1:16686/` |
| HAProxy stats | `http://127.0.0.1:8404/` |

Las contraseñas predeterminadas de noVNC, mitmweb y el dashboard son `plano-demo`; se cambian en `.env`. El usuario predeterminado del dashboard es `admin`.

## 4. Diagnóstico

```bash
./scripts/mac-diagnose.sh
./scripts/smoke-test.sh
./scripts/test-free-web-fixture.sh
```

El diagnóstico debe mostrar **18 bindings en `host-publisher`**, **cero bindings directos en trece servicios internos** y quince imágenes `linux/arm64`. La suite funcional debe terminar en `Resultado: 34 PASS, 0 FAIL`; el fixture del navegador debe terminar en `2 PASS, 0 FAIL`.

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
lsof -nP -iTCP:6083 -sTCP:LISTEN
lsof -nP -iTCP:10700 -sTCP:LISTEN
```

No cambie los puertos internos de los contenedores; modifique únicamente los valores del host, por ejemplo `CHATGPT_NOVNC_PORT=16080`.

## 6. Evidencia de compatibilidad

El perfil Compose final declara y valida quince servicios `linux/arm64` y dieciocho bindings concentrados en HAProxy. La actualización de auditoría y extensión fue ejecutada funcionalmente en un host de validación Linux: 34 controles end-to-end, 2 escenarios del Chromium real, streaming SSE, TLS interceptado, tópicos, redacción y contenido correlacionado. El escritorio Gemini reutiliza la misma imagen multi-arquitectura ya validada para Apple Silicon. La comprobación nativa final debe ejecutarse en el Mac M3 mediante `./scripts/mac-up.sh`, que falla si una imagen no es arm64 o falta un binding. Los resultados funcionales están en `artifacts/audit-dashboard-smoke-test-final.txt`, `artifacts/free-web-fixture-test-final.txt` y `artifacts/audit-dashboard-visual-validation.md`.

## Referencias

[1]: https://docs.docker.com/desktop/setup/install/mac-install/ "Install Docker Desktop on Mac"
[2]: https://docs.docker.com/build/building/multi-platform/ "Multi-platform builds"
[3]: https://docs.docker.com/engine/network/port-publishing/ "Port publishing and mapping"
[4]: https://www.haproxy.com/documentation/haproxy-configuration-tutorials/proxying-essentials/dns-resolution/ "HAProxy — DNS resolution"
[5]: https://docs.haproxy.org/3.2/configuration.html "HAProxy 3.2 Configuration Manual"
