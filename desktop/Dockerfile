FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
ARG NOVNC_VERSION=v1.7.0
ARG WEBSOCKIFY_VERSION=0.13.0

ENV DISPLAY=:1 \
    HOME=/home/demo \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates chromium curl dbus-x11 git libnss3-tools netcat-openbsd \
      openssl procps python3 python3-pip sudo supervisor tini wget \
      x11vnc xfce4 xfce4-terminal xvfb \
    && pip3 install --break-system-packages --no-cache-dir "websockify==${WEBSOCKIFY_VERSION}" \
    && git clone --depth 1 --branch "${NOVNC_VERSION}" https://github.com/novnc/noVNC.git /opt/novnc \
    && useradd --create-home --uid 10010 --shell /bin/bash demo \
    && mkdir -p /home/demo/.config/chromium /home/demo/.pki/nssdb /home/demo/.vnc /opt/governance-extension \
    && chown -R demo:demo /home/demo \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/*

COPY start-desktop.sh /usr/local/bin/start-desktop.sh
COPY extension/ /opt/governance-extension/
RUN chmod 0755 /usr/local/bin/start-desktop.sh && chmod -R a+rX /opt/governance-extension

EXPOSE 6080 5900
HEALTHCHECK --interval=15s --timeout=5s --retries=20 CMD ["curl", "-fsS", "http://127.0.0.1:6080/vnc.html"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-desktop.sh"]
