ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache bash curl openvpn openssl iproute2 jq python3

WORKDIR /app
COPY run.sh /app/run.sh
COPY vpn.sh /app/vpn.sh
COPY supervisor_poc.py /app/supervisor_poc.py
RUN sed -i 's/\r$//' /app/run.sh /app/vpn.sh \
    && bash -n /app/run.sh /app/vpn.sh \
    && python3 -m py_compile /app/supervisor_poc.py \
    && chmod +x /app/run.sh /app/vpn.sh

ENV LANG=C.UTF-8
ENV MAC_ADDRESS=""

CMD ["/app/run.sh"]