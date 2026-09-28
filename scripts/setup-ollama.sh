#!/usr/bin/env bash
# Prepara el Ollama nativo del host para la analítica de uso (Economic Index local).
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi
MODEL="${ANALYTICS_MODEL:-qwen2.5:7b-instruct}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama no está instalado. Instálelo desde https://ollama.com/download (o: brew install ollama)." >&2
  exit 1
fi

if ! curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama no responde en 127.0.0.1:11434. Inicie la app de Ollama o ejecute 'ollama serve' y reintente." >&2
  exit 1
fi

if ollama list | awk 'NR>1 {print $1}' | grep -qx "$MODEL"; then
  echo "Modelo $MODEL ya disponible."
else
  echo "Descargando $MODEL (unos 5 GB)..."
  ollama pull "$MODEL"
fi

echo "Precargando el modelo en memoria..."
curl -fsS --max-time 300 http://127.0.0.1:11434/api/generate \
  -d "{\"model\":\"$MODEL\",\"prompt\":\"ok\",\"stream\":false,\"keep_alive\":\"30m\"}" >/dev/null
echo "Ollama listo. Ollama escucha solo en loopback; el puente de host-publisher lo expone únicamente a audit-dashboard."
