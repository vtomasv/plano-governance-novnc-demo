FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 audit \
    && useradd --uid 10001 --gid 10001 --home-dir /app --no-create-home --shell /usr/sbin/nologin audit \
    && mkdir -p /data /app/static \
    && chown -R audit:audit /data /app

COPY --chown=audit:audit app.py ./
COPY --chown=audit:audit static/ ./static/

USER 10001:10001
EXPOSE 10700
HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=5s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10700/health', timeout=3)"]

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10700", "--workers", "1"]
