ARG BUILD_FROM
FROM $BUILD_FROM

# Il Supervisor passa la version di config.yaml; finisce in addon_version dell'heartbeat
ARG BUILD_VERSION=dev
ENV ADDON_VERSION=$BUILD_VERSION \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY mqtt_bridge /app/mqtt_bridge
COPY run.sh /app/run.sh
RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]
