# Validación visual del publisher HAProxy

Se abrió noVNC a través del puerto frontal de HAProxy y la conexión pasó de `Conectando...` al título `chrome - noVNC`. El canvas VNC mostró el escritorio Xfce con Chromium operativo. Esto confirma que el modo TCP preserva el upgrade WebSocket y la sesión bidireccional de larga duración.

Validación complementaria por protocolo:

```text
HTTP/1.1 101 Switching Protocols
Server: WebSockify Python/3.11.2
Upgrade: websocket
Connection: Upgrade
```

La prueba se ejecutó sobre un publisher temporal con puertos alternativos debido a las limitaciones de bridge/netfilter del sandbox. La configuración de producción para Mac conserva la misma configuración HAProxy y publica `6080`, `6081` y `6082` en loopback.
