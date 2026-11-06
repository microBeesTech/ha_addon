#!/usr/bin/with-contenv /bin/sh
# with-contenv: s6-overlay avvia il servizio con un ambiente pulito; cosi' riceve le variabili del container,
# compreso SUPERVISOR_TOKEN (necessario per l'API di Home Assistant).
# Non si usa bashio: l'immagine base-python non lo include; qui serve solo l'ambiente del container.
exec python3 -m mqtt_bridge
