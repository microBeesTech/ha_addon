ARG BUILD_FROM
FROM $BUILD_FROM

# Installa dipendenze
RUN apk add --no-cache bash curl openvpn openssl iproute2

WORKDIR /app
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

# Mantieni compatibilità con variabili d’ambiente di Home Assistant
ENV LANG C.UTF-8
ENV MAC_ADDRESS=""

CMD ["/app/run.sh"]
