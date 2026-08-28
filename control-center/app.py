from __future__ import annotations

import asyncio
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI(title="Plano Governance Demo Control Center", version="1.2.0")
STATIC_DIR = Path(__file__).parent / "static"
STARTED_AT = time.time()

HTTP_TARGETS: dict[str, dict[str, Any]] = {
    "plano_gateway": {
        "label": "Plano LLM Gateway",
        "url": "http://plano:12000/healthz",
        "public_port_env": "PLANO_PORT",
        "public_port_default": 12000,
        "public_path": "/healthz",
        "group": "governance",
        "healthy_detail": "Listener de modelos de Plano disponible",
    },
    "plano_admin": {
        "label": "Plano / Envoy Admin",
        "url": "http://plano:9901/ready",
        "public_port_env": "PLANO_ADMIN_PORT",
        "public_port_default": 19901,
        "public_path": "/",
        "group": "governance",
        "healthy_detail": "Envoy Admin está LIVE",
    },
    "policy_guard": {
        "label": "Policy Guard",
        "url": "http://policy-guard:10500/health",
        "public_port_env": "POLICY_GUARD_PORT",
        "public_port_default": 10500,
        "public_path": "/",
        "group": "governance",
    },
    "governed_agent": {
        "label": "Agente gobernado",
        "url": "http://governed-agent:10600/health",
        "public_port_env": "GOVERNED_AGENT_PORT",
        "public_port_default": 10600,
        "public_path": "/",
        "group": "clients",
    },
    "provider_sim": {
        "label": "Proveedor LLM simulado",
        "url": "http://provider-sim:10501/health",
        "public_port_env": "PROVIDER_SIM_PORT",
        "public_port_default": 10501,
        "public_path": "/",
        "group": "upstream",
    },
    "desktop_chatgpt": {
        "label": "Escritorio ChatGPT / noVNC",
        "url": "http://desktop-chatgpt:6080/vnc.html",
        "public_port_env": "CHATGPT_NOVNC_PORT",
        "public_port_default": 6080,
        "public_path": "/vnc.html?autoconnect=1&resize=remote",
        "group": "clients",
        "healthy_detail": "Página noVNC disponible; conexión VNC lista",
    },
    "desktop_claude": {
        "label": "Escritorio Claude / noVNC",
        "url": "http://desktop-claude:6080/vnc.html",
        "public_port_env": "CLAUDE_NOVNC_PORT",
        "public_port_default": 6081,
        "public_path": "/vnc.html?autoconnect=1&resize=remote",
        "group": "clients",
        "healthy_detail": "Página noVNC disponible; conexión VNC lista",
    },
    "desktop_grok": {
        "label": "Escritorio Grok / noVNC",
        "url": "http://desktop-grok:6080/vnc.html",
        "public_port_env": "GROK_NOVNC_PORT",
        "public_port_default": 6082,
        "public_path": "/vnc.html?autoconnect=1&resize=remote",
        "group": "clients",
        "healthy_detail": "Página noVNC disponible; conexión VNC lista",
    },
    "jaeger": {
        "label": "Jaeger",
        "url": "http://jaeger:16686/",
        "public_port_env": "JAEGER_UI_PORT",
        "public_port_default": 16686,
        "public_path": "/",
        "group": "observability",
        "healthy_detail": "Interfaz de trazas disponible",
    },
    "mitmweb": {
        "label": "mitmweb",
        "url": "http://proxy-interceptor:8081/",
        "public_port_env": "MITMPROXY_UI_PORT",
        "public_port_default": 8081,
        "public_path": "/",
        "group": "observability",
        "accepted_statuses": [200, 302, 401, 403],
        "healthy_detail": "Interfaz activa; autenticación requerida",
    },
}

if os.getenv("INCLUDE_HOST_PUBLISHER", "false").lower() == "true":
    HTTP_TARGETS["host_publisher"] = {
        "label": "Publisher de host / HAProxy",
        "url": "http://host-publisher:8404/",
        "public_port_env": "HOST_PUBLISHER_STATS_PORT",
        "public_port_default": 8404,
        "public_path": "/",
        "group": "observability",
        "healthy_detail": "Publisher único activo; backends y estadísticas disponibles",
    }


def public_port(item: dict[str, Any]) -> int:
    return int(os.getenv(item["public_port_env"], str(item["public_port_default"])))


def internal_url(url: str) -> str:
    if os.getenv("CONTROL_CENTER_TARGET_MODE", "docker") != "host":
        return url
    parsed = urlsplit(url)
    port = parsed.port
    netloc = f"127.0.0.1:{port}" if port else "127.0.0.1"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


async def probe_http(name: str, item: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    accepted = set(item.get("accepted_statuses", [200]))
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=False) as client:
            response = await client.get(internal_url(item["url"]))
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        healthy = response.status_code in accepted
        raw_detail = response.text.strip().replace("\n", " ")[:180]
        detail = item.get("healthy_detail", raw_detail) if healthy else raw_detail
        return {
            "id": name,
            "label": item["label"],
            "group": item["group"],
            "healthy": healthy,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "detail": detail or f"HTTP {response.status_code}",
            "public_port": public_port(item),
            "public_path": item["public_path"],
        }
    except Exception as exc:  # diagnóstico: el tipo resumido es suficiente
        return {
            "id": name,
            "label": item["label"],
            "group": item["group"],
            "healthy": False,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": f"{type(exc).__name__}: {str(exc)[:140]}",
            "public_port": public_port(item),
            "public_path": item["public_path"],
        }


async def probe_tcp() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proxy_host = "127.0.0.1" if os.getenv("CONTROL_CENTER_TARGET_MODE", "docker") == "host" else "proxy-interceptor"
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy_host, 8080), timeout=3.0
        )
        writer.close()
        await writer.wait_closed()
        return {
            "id": "mitmproxy",
            "label": "Proxy TLS / mitmproxy",
            "group": "governance",
            "healthy": True,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": "TCP 8080 disponible dentro de la red control",
            "public_port": None,
            "public_path": None,
        }
    except (OSError, asyncio.TimeoutError) as exc:
        return {
            "id": "mitmproxy",
            "label": "Proxy TLS / mitmproxy",
            "group": "governance",
            "healthy": False,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": f"{type(exc).__name__}: {str(exc)[:140]}",
            "public_port": None,
            "public_path": None,
        }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "control-center", "uptime_seconds": int(time.time() - STARTED_AT)}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    results = await asyncio.gather(
        *(probe_http(name, item) for name, item in HTTP_TARGETS.items()), probe_tcp()
    )
    services = list(results)
    healthy = sum(1 for item in services if item["healthy"])
    return {
        "status": "ok" if healthy == len(services) else "degraded",
        "healthy": healthy,
        "total": len(services),
        "checked_at_epoch": int(time.time()),
        "services": services,
    }


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {
        "bind_address": os.getenv("BIND_ADDRESS", "127.0.0.1"),
        "policy_fail_mode": os.getenv("POLICY_FAIL_MODE", "closed"),
        "prompt_body_logging": os.getenv("LOG_PROMPT_BODIES", "false").lower() == "true",
        "vnc_password_source": ".env: VNC_PASSWORD",
        "mitmweb_password_source": ".env: MITMWEB_PASSWORD",
        "plano_config_file": "plano/config.local.yaml",
        "port_config_file": ".env",
        "policy_source": "policy-guard/app.py",
        "apply_command": "./scripts/mac-up.sh" if os.getenv("INCLUDE_HOST_PUBLISHER", "false").lower() == "true" else "./scripts/up.sh",
        "publication_mode": "single-haproxy" if os.getenv("INCLUDE_HOST_PUBLISHER", "false").lower() == "true" else "direct-bindings",
        "hostname": socket.gethostname(),
    }
