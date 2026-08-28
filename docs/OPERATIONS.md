# Guía operativa y de diagnóstico

## Superficies publicadas

El despliegue soportado se inicia mediante los scripts que fijan explícitamente el Compose principal.

En **macOS Apple Silicon M1/M2/M3/M4**:

```bash
git pull
chmod +x scripts/*.sh
./scripts/down.sh
./scripts/mac-up.sh
./scripts/mac-diagnose.sh
```

En Linux use `./scripts/up.sh`; Windows conserva scripts PowerShell secundarios. En Mac, `mac-up.sh` combina el Compose principal con `docker-compose.mac-arm64.yml` y `docker-compose.mac-publisher.yml`, exige imágenes `linux/arm64`, usa `--force-recreate` y comprueba que los dieciséis `PortBindings` existan exclusivamente en `host-publisher`. No combine el Compose principal con `dev/docker-compose.sandbox-internal.yml`. Ese archivo es un workaround del entorno de desarrollo y elimina los mapeos de Docker mediante `ports: !reset []`.

| Puerto predeterminado | Servicio | Uso |
|---:|---|---|
| `10000` | Control Center | Panel consolidado de salud, enlaces y configuración |
| `6080` | ChatGPT noVNC | Escritorio gráfico en Chromium |
| `6081` | Claude noVNC | Escritorio gráfico en Chromium |
| `6082` | Grok noVNC | Escritorio gráfico en Chromium |
| `12000` | Plano model listener | API LLM gobernada |
| `8001` | Plano agent listener | Listener del agente de Plano |
| `19901` | Envoy Admin de Plano | Diagnóstico de listeners, clusters y métricas |
| `10500` | Policy Guard | Salud, decisiones anonimizadas y métricas |
| `10501` | Provider Sim | Salud y contador de llamadas upstream |
| `10600` | Governed Agent | Interfaz directa y API del agente |
| `16686` | Jaeger | Trazas de Plano |
| `8081` | mitmweb | Inspección de flujos del proxy TLS |
| `8404` | HAProxy stats | Estado de cada backend publicado |

En Mac, todos los puertos de `host-publisher` están fijados deliberadamente a `127.0.0.1`; cambiar `BIND_ADDRESS` no los expone a la LAN. Un acceso remoto requiere un diseño separado con autenticación, firewall o VPN.

## Qué configurar en `http://127.0.0.1:19901/`

No se configura nada desde esa página. `19901` mapea el puerto interno `9901` de **Envoy Admin**, generado por Plano. Es una interfaz operativa de solo diagnóstico. Sus rutas más útiles son:

| Ruta | Finalidad |
|---|---|
| `/ready` | Estado `LIVE` del dataplane |
| `/server_info` | Versión, uptime y estado de Envoy |
| `/listeners` | Listeners efectivos, incluidos `12000` y `8001` |
| `/clusters` | Filtros, proveedores y servicios upstream conocidos |
| `/config_dump` | Configuración Envoy efectiva generada por Plano |
| `/stats/prometheus` | Métricas en formato Prometheus |

La configuración fuente se realiza en [`plano/config.local.yaml`](../plano/config.local.yaml):

| Sección | Qué controla |
|---|---|
| `filters` | URL del guardrail HTTP `argentina_president_guard` |
| `listeners` | Listener LLM `12000`, listener de agente `8001` y cadenas de filtros |
| `model_providers` | ChatGPT, Claude y Grok simulados o reales |
| `model_aliases` | Alias visibles para clientes |
| `routing_preferences` | Orden de modelos según preferencia |
| `tracing` | Exportación OTLP a Jaeger |

Después de editarla, aplique los cambios con:

```bash
./scripts/mac-up.sh
./scripts/compose.sh logs --tail=200 plano
curl -fsS http://127.0.0.1:12000/healthz
curl -fsS http://127.0.0.1:19901/ready
```

## Contraseña de mitmweb en `8081`

mitmweb tiene autenticación intencional. La contraseña predeterminada es:

```text
plano-demo
```

El valor real se encuentra en `.env`:

```bash
grep '^MITMWEB_PASSWORD=' .env
```

Para cambiarlo, edite `MITMWEB_PASSWORD` y recree exclusivamente el proxy:

```bash
./scripts/mac-up.sh
```

La contraseña noVNC es independiente y está en `VNC_PASSWORD`. `./scripts/up.sh` y `./scripts/diagnose.sh` muestran ambos valores en la terminal local.

## Diagnóstico rápido de puertos ausentes

Con el perfil Mac actual, los escritorios, Plano, Policy Guard y los demás backends aparecen **sin puertos por diseño**. Docker Desktop debe mostrar los bindings únicamente en `host-publisher-1`. Esto reduce la superficie publicada y evita depender de cómo Docker Desktop representa bindings sobre redes internas.

La causa puede ser un `COMPOSE_FILE` heredado, un override externo, `docker compose run`, el botón Run sobre una imagen o contenedores obsoletos. Los scripts nuevos neutralizan `COMPOSE_FILE` mediante `-f /ruta/absoluta/docker-compose.yml` y muestran la etiqueta `com.docker.compose.project.config_files` registrada por Docker.

En Mac:

```bash
./scripts/check-publisher-ports.sh
./scripts/mac-diagnose.sh
```

En Linux sin publisher use `./scripts/check-runtime-ports.sh` y `./scripts/diagnose.sh`.

En PowerShell:

```powershell
.\scripts\diagnose.ps1
```

Para recuperar la pila en un Mac M3:

```bash
./scripts/down.sh
./scripts/mac-up.sh
./scripts/mac-diagnose.sh
```

Para recuperar en Linux use `./scripts/up.sh`; en Windows use `scripts/down.ps1` y `scripts/up.ps1`.

En Docker Desktop, `host-publisher-1` debe mostrar `6080`, `6081`, `6082`, `10000`, `10500`, `10501`, `10600`, `16686`, `18443`, `19901`, `8081` y `8404`; los demás contenedores no deben mostrar bindings. Si el mapeo existe pero la URL no responde, revise:

```bash
./scripts/compose.sh logs --tail=200 desktop-chatgpt
./scripts/compose.sh logs --tail=200 desktop-claude
./scripts/compose.sh logs --tail=200 desktop-grok
./scripts/up.sh
```

En Docker Desktop, confirme que el motor esté en modo **Linux containers** y que ningún proceso local esté usando esos puertos. Puede cambiar cualquier puerto del host en `.env` sin modificar el puerto interno `6080` de cada contenedor.
