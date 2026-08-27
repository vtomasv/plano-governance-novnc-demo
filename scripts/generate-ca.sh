#!/usr/bin/env sh
set -eu

OUT_DIR="${1:-/certs}"
FORCE="${FORCE_CA_REGEN:-0}"
DAYS_ROOT="${CA_DAYS:-3650}"
DAYS_LEAF="${LEAF_DAYS:-825}"

ROOT_KEY="$OUT_DIR/plano-demo-root-ca.key"
ROOT_CERT="$OUT_DIR/plano-demo-root-ca.crt"
LEAF_KEY="$OUT_DIR/demo-upstream.key"
LEAF_CERT="$OUT_DIR/demo-upstream.crt"
MITM_DIR="$OUT_DIR/mitmproxy"

mkdir -p "$OUT_DIR" "$MITM_DIR"
umask 077

if [ "$FORCE" != "1" ] && [ -s "$ROOT_KEY" ] && [ -s "$ROOT_CERT" ] && [ -s "$MITM_DIR/mitmproxy-ca.pem" ]; then
  echo "CA existente: $ROOT_CERT"
  openssl x509 -in "$ROOT_CERT" -noout -subject -fingerprint -sha256
  exit 0
fi

rm -f "$ROOT_KEY" "$ROOT_CERT" "$OUT_DIR/root-ca.srl" \
  "$LEAF_KEY" "$LEAF_CERT" "$OUT_DIR/demo-upstream.csr" \
  "$OUT_DIR/demo-upstream.ext" "$MITM_DIR"/mitmproxy-ca*

openssl genrsa -out "$ROOT_KEY" 4096
openssl req -x509 -new -nodes \
  -key "$ROOT_KEY" \
  -sha256 \
  -days "$DAYS_ROOT" \
  -out "$ROOT_CERT" \
  -subj "/C=AR/O=Plano Governance Lab/OU=Controlled TLS Interception/CN=Plano Demo Root CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash"

openssl genrsa -out "$LEAF_KEY" 2048
openssl req -new \
  -key "$LEAF_KEY" \
  -out "$OUT_DIR/demo-upstream.csr" \
  -subj "/C=AR/O=Plano Governance Lab/OU=Demo Upstreams/CN=chatgpt.demo.local"

cat > "$OUT_DIR/demo-upstream.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=@alt_names

[alt_names]
DNS.1=chatgpt.demo.local
DNS.2=claude.demo.local
DNS.3=grok.demo.local
DNS.4=provider-sim
DNS.5=localhost
IP.1=127.0.0.1
EOF

openssl x509 -req \
  -in "$OUT_DIR/demo-upstream.csr" \
  -CA "$ROOT_CERT" \
  -CAkey "$ROOT_KEY" \
  -CAcreateserial \
  -CAserial "$OUT_DIR/root-ca.srl" \
  -days "$DAYS_LEAF" \
  -sha256 \
  -extfile "$OUT_DIR/demo-upstream.ext" \
  -out "$LEAF_CERT"

# mitmproxy reconoce esta pareja de nombres dentro de su confdir. El archivo
# mitmproxy-ca.pem contiene la clave privada seguida del certificado de la CA.
cat "$ROOT_KEY" "$ROOT_CERT" > "$MITM_DIR/mitmproxy-ca.pem"
cp "$ROOT_CERT" "$MITM_DIR/mitmproxy-ca-cert.pem"
openssl pkcs12 -export \
  -inkey "$ROOT_KEY" \
  -in "$ROOT_CERT" \
  -out "$MITM_DIR/mitmproxy-ca-cert.p12" \
  -passout pass:

chmod 0600 "$ROOT_KEY" "$LEAF_KEY" "$MITM_DIR/mitmproxy-ca.pem" "$MITM_DIR/mitmproxy-ca-cert.p12"
chmod 0644 "$ROOT_CERT" "$LEAF_CERT" "$MITM_DIR/mitmproxy-ca-cert.pem"
rm -f "$OUT_DIR/demo-upstream.csr" "$OUT_DIR/demo-upstream.ext"

echo "CA raíz generada: $ROOT_CERT"
openssl x509 -in "$ROOT_CERT" -noout -subject -issuer -dates -fingerprint -sha256
echo "Certificado de upstream de prueba: $LEAF_CERT"
openssl verify -CAfile "$ROOT_CERT" "$LEAF_CERT"
