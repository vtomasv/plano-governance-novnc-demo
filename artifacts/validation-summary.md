# Informe de validación de la corrección operativa

**Fecha:** 27 de agosto de 2026  
**Resultado general:** aprobado

| Área | Resultado | Evidencia |
|---|---:|---|
| Tests unitarios del filtro | 10/10 PASS | `python3 -m pytest -q policy-guard/test_policy.py` |
| Suite end-to-end ampliada | 23/23 PASS | `artifacts/smoke-test-bindings-fix.txt` |
| Validación declarativa de puertos | PASS | `scripts/validate_compose.py` |
| PortBindings creados por Docker | PASS | `artifacts/runtime-port-regression.txt` |
| Control Center | 11/11 saludables | Validado por `artifacts/smoke-test-bindings-fix.txt` |
| ChatGPT noVNC | PASS | Host `6080` → contenedor `6080` |
| Claude noVNC | PASS | Host `6081` → contenedor `6080` |
| Grok noVNC | PASS | Host `6082` → contenedor `6080` |
| Plano Gateway | PASS | Host `12000` → contenedor `12000`; `/healthz` responde 200 |
| Plano Agent Listener | PASS | Host `8001` → contenedor `8001` |
| Plano/Envoy Admin | PASS | Host `19901` → contenedor `9901`; `/ready` responde `LIVE` |
| mitmweb | PASS | Host `8081` → contenedor `8081`; login validado con `MITMWEB_PASSWORD` |
| Política Milei/Miley/Mliey | PASS | HTTP 403, texto estable y cero llamadas upstream |
| Prevención de fuga | PASS | Patrón de API key bloqueado |
| Streaming | PASS | Chunks SSE y `[DONE]` preservados |
| MITM TLS controlado | PASS | Solicitud permitida y denegada con CA confiada |

## Causa raíz corregida

El Compose principal publicaba los puertos, pero el archivo `docker-compose.sandbox.yml` podía combinarse accidentalmente. Ese override usaba `network_mode: host` y eliminaba todos los mapeos mediante `ports: !reset []`. Se movió a `dev/docker-compose.sandbox-internal.yml` y se marcó como no apto para estaciones de trabajo o Docker Desktop.

## Verificaciones realizadas

Docker materializó los siguientes bindings en una pila normal creada específicamente para la prueba:

```text
desktop-chatgpt  127.0.0.1:6080 -> 6080/tcp
desktop-claude   127.0.0.1:6081 -> 6080/tcp
desktop-grok     127.0.0.1:6082 -> 6080/tcp
plano             127.0.0.1:12000 -> 12000/tcp
plano             127.0.0.1:8001 -> 8001/tcp
plano             127.0.0.1:19901 -> 9901/tcp
proxy-interceptor 127.0.0.1:8081 -> 8081/tcp
control-center    127.0.0.1:10000 -> 10000/tcp
```

La ejecución funcional dentro del sandbox requirió el override interno debido a las limitaciones de bridge/netfilter anidado del kernel. Esa ejecución equivalente completó 23 pruebas y el Control Center informó 11 de 11 componentes saludables.

## Operación recomendada

```bash
cp -n .env.example .env
./scripts/up.sh
./scripts/diagnose.sh
./scripts/smoke-test.sh
```

No se debe añadir `-f dev/docker-compose.sandbox-internal.yml` en la máquina del usuario.
