# Guía operativa y de diagnóstico

## Superficies publicadas

El despliegue soportado se inicia únicamente con:

```bash
cp .env.example .env
docker compose up -d --build
./scripts/diagnose.sh
```

No combine el Compose principal con `dev/docker-compose.sandbox-internal.yml`. Ese archivo es un workaround del entorno de desarrollo y elimina los mapeos de Docker mediante `ports: !reset []`.

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

Todos los puertos se vinculan de forma predeterminada a `127.0.0.1`. Cambie `BIND_ADDRESS=0.0.0.0` solo si necesita acceso remoto y cuenta con firewall, VPN o un reverse proxy autenticado.

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
docker compose up -d --force-recreate plano governed-agent proxy-interceptor
docker compose logs --tail=200 plano
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
docker compose up -d --force-recreate proxy-interceptor
```

La contraseña noVNC es independiente y está en `VNC_PASSWORD`. `./scripts/up.sh` y `./scripts/diagnose.sh` muestran ambos valores en la terminal local.

## Diagnóstico rápido de puertos ausentes

Primero confirme que está usando solo el Compose principal:

```bash
docker compose config --services
docker compose config | grep -A5 -E 'desktop-(chatgpt|claude|grok):'
```

Después ejecute:

```bash
docker compose ps -a
docker compose port desktop-chatgpt 6080
docker compose port desktop-claude 6080
docker compose port desktop-grok 6080
./scripts/diagnose.sh
```

Los resultados esperados de `docker compose port` terminan respectivamente en `6080`, `6081` y `6082`. Si el mapeo existe pero la URL no responde, revise:

```bash
docker compose logs --tail=200 desktop-chatgpt
docker compose logs --tail=200 desktop-claude
docker compose logs --tail=200 desktop-grok
docker compose up -d --build --force-recreate
```

En Docker Desktop, confirme que el motor esté en modo **Linux containers** y que ningún proceso local esté usando esos puertos. Puede cambiar cualquier puerto del host en `.env` sin modificar el puerto interno `6080` de cada contenedor.
