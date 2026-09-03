#!/usr/bin/env bash
set -Eeuo pipefail

PROVIDER="${PROVIDER:-chatgpt}"
VNC_PASSWORD="${VNC_PASSWORD:-plano-demo}"
PROXY_URL="${PROXY_URL:-http://proxy-interceptor:8080}"
CA_FILE="${CA_FILE:-/certs/plano-demo-root-ca.crt}"
START_URL="${START_URL:-http://governed-agent:10600/?provider=${PROVIDER}}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"

cleanup() {
  jobs -pr | xargs -r kill || true
}
trap cleanup EXIT INT TERM

if [[ ! -s "$CA_FILE" ]]; then
  echo "Falta la CA raíz en $CA_FILE" >&2
  exit 1
fi

install -m 0644 "$CA_FILE" /usr/local/share/ca-certificates/plano-demo-root-ca.crt
update-ca-certificates >/tmp/update-ca-certificates.log 2>&1

install -d -m 0700 -o demo -g demo /home/demo/.pki/nssdb /home/demo/.vnc /home/demo/.config/chromium
if [[ ! -s /home/demo/.pki/nssdb/cert9.db ]]; then
  runuser -u demo -- certutil -N -d sql:/home/demo/.pki/nssdb --empty-password
fi
runuser -u demo -- certutil -D -d sql:/home/demo/.pki/nssdb -n "Plano Demo Root CA" >/dev/null 2>&1 || true
runuser -u demo -- certutil -A -d sql:/home/demo/.pki/nssdb -n "Plano Demo Root CA" -t "C,," -i "$CA_FILE"

x11vnc -storepasswd "$VNC_PASSWORD" /home/demo/.vnc/passwd >/dev/null
chown demo:demo /home/demo/.vnc/passwd
chmod 0600 /home/demo/.vnc/passwd

rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvfb :1 -screen 0 "${SCREEN_GEOMETRY:-1366x768x24}" -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
for _ in $(seq 1 30); do
  xdpyinfo -display :1 >/dev/null 2>&1 && break
  sleep 0.2
done

runuser -u demo -- env DISPLAY=:1 dbus-run-session -- xfwm4 --replace >/tmp/xfce.log 2>&1 &
sleep 2

x11vnc -display :1 -rfbport "$VNC_PORT" -rfbauth /home/demo/.vnc/passwd -forever -shared -localhost -noxdamage >/tmp/x11vnc.log 2>&1 &

# El perfil y la extensión permanecen dentro del volumen del escritorio. Los
# dominios internos evitan el proxy; todo destino público atraviesa mitmproxy.
install -d -m 0755 /etc/chromium/policies/managed
cat > /etc/chromium/policies/managed/plano-startup.json <<EOF
{
  "HomepageIsNewTabPage": false,
  "HomepageLocation": "$START_URL",
  "RestoreOnStartup": 4,
  "RestoreOnStartupURLs": ["$START_URL"],
  "TranslateEnabled": false,
  "BrowserSignin": 0,
  "DefaultBrowserSettingEnabled": false,
  "PromotionalTabsEnabled": false
}
EOF

runuser -u demo -- env DISPLAY=:1 HOME=/home/demo chromium \
  --user-data-dir=/home/demo/.config/chromium \
  --proxy-server="$PROXY_URL" \
  '--proxy-bypass-list=localhost;127.0.0.1;governed-agent;audit-dashboard;plano;policy-guard;provider-sim' \
  --disable-background-networking \
  --disable-component-update \
  --disable-default-apps \
  --disable-dev-shm-usage \
  --disable-features=Translate \
  --disable-sync \
  --disable-extensions-except=/opt/governance-extension \
  --load-extension=/opt/governance-extension \
  --no-first-run \
  --no-sandbox \
  --disable-session-crashed-bubble \
  --hide-crash-restore-bubble \
  --new-window \
  --password-store=basic \
  --test-type \
  --window-size=1320,720 \
  "$START_URL" >/tmp/chromium.log 2>&1 &

exec websockify --web=/opt/novnc "$NOVNC_PORT" "localhost:$VNC_PORT"
