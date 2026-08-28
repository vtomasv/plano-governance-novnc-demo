# Changelog

## 1.1.0 — 2026-08-27

Esta versión corrige la experiencia de despliegue y diagnóstico en estaciones de trabajo.

| Cambio | Resultado |
|---|---|
| Puertos noVNC | Se validan y materializan `6080`, `6081` y `6082` en el Compose principal |
| Override interno | Se movió a `dev/` y ahora exige una variable de habilitación para impedir uso accidental |
| Control Center | Nuevo panel en `http://127.0.0.1:10000` con 11 sondas internas y enlaces operativos |
| Plano | Healthcheck en `/healthz`; Envoy Admin `19901` documentado como diagnóstico |
| mitmweb | Contraseña separada en `MITMWEB_PASSWORD`; login probado automáticamente |
| Servicios auxiliares | Índices JSON para Policy Guard y Provider Sim; healthchecks para Jaeger y upstream TLS |
| Diagnóstico | Nuevo `scripts/diagnose.sh` y validación automática de PortBindings |
| Portabilidad | Scripts compatibles con Docker Desktop y Linux, con uso condicional de `sudo` |
| Pruebas | Suite ampliada de 16 a 23 comprobaciones end-to-end; resultado 23 PASS, 0 FAIL |

## 1.0.0 — 2026-08-27

Versión inicial de la demo con Plano, noVNC, filtro de gobierno, proxy TLS controlado, proveedor simulado y Jaeger.
