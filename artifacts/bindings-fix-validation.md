# Validación de la corrección de PortBindings

**Fecha:** 27 de agosto de 2026  
**Resultado:** aprobado

## Fallo reproducido

Se creó una pila de prueba con un override externo que eliminó los puertos de todos los servicios salvo Plano. El resultado reprodujo el patrón observado: los contenedores existían, pero Docker registró `HostConfig.PortBindings={}` para Control Center, escritorios, Policy Guard, proveedores, agente, Jaeger y mitmweb.

La comprobación `scripts/check-runtime-ports.sh` rechazó correctamente ese estado y mostró los dos archivos Compose registrados en la etiqueta `com.docker.compose.project.config_files`. La salida se conserva en `artifacts/runtime-port-contaminated.txt`.

## Recuperación validada

La misma pila se eliminó y recreó con el wrapper que fuerza exclusivamente `docker-compose.yml`. El resultado fue:

| Servicio | Binding validado |
|---|---|
| Control Center | `127.0.0.1:10000 → 10000/tcp` |
| ChatGPT noVNC | `127.0.0.1:6080 → 6080/tcp` |
| Claude noVNC | `127.0.0.1:6081 → 6080/tcp` |
| Grok noVNC | `127.0.0.1:6082 → 6080/tcp` |
| Plano | `12000 → 12000`, `8001 → 8001`, `19901 → 9901` |
| Policy Guard | `10500 → 10500` |
| Provider Sim | `10501 → 10501` |
| Provider TLS Sim | `18443 → 8443` |
| Governed Agent | `10600 → 10600` |
| Jaeger | `16686 → 16686`, `4317 → 4317`, `4318 → 4318` |
| mitmweb | `8081 → 8081` |

La salida completa se conserva en `artifacts/runtime-port-regression.txt`.

## Regresiones ejecutadas

| Prueba | Resultado |
|---|---:|
| Compose principal y mapeos declarados | PASS |
| Aislamiento frente a `COMPOSE_FILE` heredado | PASS |
| Estado runtime contaminado | Rechazado correctamente |
| Recreación runtime limpia | 15 bindings PASS |
| Tests unitarios de política | 10 PASS, 0 FAIL |
| Suite funcional | 23 PASS, 0 FAIL |
| Sintaxis PowerShell 7.5 | PASS |
| noVNC 6080–6082 | PASS |
| Plano Admin | PASS |
| Autenticación mitmweb | PASS |
| Streaming y MITM TLS | PASS |
| Bloqueo Milei/Miley/Mliey sin upstream | PASS |

## Comandos soportados

Windows/Docker Desktop:

```powershell
.\scripts\down.ps1
.\scripts\up.ps1
.\scripts\diagnose.ps1
```

Linux o macOS:

```bash
./scripts/compose.sh down --remove-orphans
./scripts/up.sh
./scripts/diagnose.sh
```
