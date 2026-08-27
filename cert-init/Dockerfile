FROM alpine:3.22.1
RUN apk add --no-cache openssl
COPY scripts/generate-ca.sh /usr/local/bin/generate-ca.sh
RUN chmod 0755 /usr/local/bin/generate-ca.sh
ENTRYPOINT ["/usr/local/bin/generate-ca.sh", "/certs"]
