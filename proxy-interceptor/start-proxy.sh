#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR="${MITM_CA_SOURCE_DIR:-/certs/mitmproxy}"
TARGET_DIR=/home/mitm/.mitmproxy
ROOT_CA="${ROOT_CA_FILE:-/certs/plano-demo-root-ca.crt}"
WEB_PASSWORD="${MITMWEB_PASSWORD:-plano-demo}"

for required in "$SOURCE_DIR/mitmproxy-ca.pem" "$SOURCE_DIR/mitmproxy-ca-cert.pem" "$ROOT_CA"; do
  if [[ ! -s "$required" ]]; then
    echo "Falta el archivo requerido: $required" >&2
    exit 1
  fi
done

install -d -m 0700 -o mitm -g mitm "$TARGET_DIR"
install -m 0600 -o mitm -g mitm "$SOURCE_DIR/mitmproxy-ca.pem" "$TARGET_DIR/mitmproxy-ca.pem"
install -m 0644 -o mitm -g mitm "$SOURCE_DIR/mitmproxy-ca-cert.pem" "$TARGET_DIR/mitmproxy-ca-cert.pem"
if [[ -s "$SOURCE_DIR/mitmproxy-ca-cert.p12" ]]; then
  install -m 0600 -o mitm -g mitm "$SOURCE_DIR/mitmproxy-ca-cert.p12" "$TARGET_DIR/mitmproxy-ca-cert.p12"
fi
cat /etc/ssl/certs/ca-certificates.crt "$ROOT_CA" > "$TARGET_DIR/upstream-ca.pem"
chown mitm:mitm "$TARGET_DIR/upstream-ca.pem"
chmod 0644 "$TARGET_DIR/upstream-ca.pem"

exec gosu mitm:mitm mitmweb \
  --listen-host 0.0.0.0 \
  --listen-port 8080 \
  --web-host 0.0.0.0 \
  --web-port 8081 \
  --set "confdir=$TARGET_DIR" \
  --set "web_password=$WEB_PASSWORD" \
  --set "connection_strategy=lazy" \
  --set "ssl_verify_upstream_trusted_ca=$TARGET_DIR/upstream-ca.pem" \
  --set "flow_detail=1" \
  --set "console_eventlog_verbosity=info" \
  --scripts /app/governance.py
