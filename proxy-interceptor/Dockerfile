FROM python:3.12.11-slim-bookworm

ARG MITMPROXY_VERSION=12.2.3
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gosu tini \
    && pip install --no-cache-dir "mitmproxy==${MITMPROXY_VERSION}" \
    && useradd --create-home --uid 10020 mitm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY governance.py ./
COPY start-proxy.sh /usr/local/bin/start-proxy.sh
RUN chmod 0755 /usr/local/bin/start-proxy.sh

EXPOSE 8080 8081
HEALTHCHECK --interval=10s --timeout=5s --retries=15 CMD ["python", "-c", "import socket; s=socket.create_connection(('127.0.0.1',8080),2); s.close()"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-proxy.sh"]
