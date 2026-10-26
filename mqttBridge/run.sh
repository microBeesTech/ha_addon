#!/usr/bin/with-contenv bashio
# with-contenv: s6-overlay avvia il servizio con un ambiente pulito; così riceve le variabili del container,
# compreso SUPERVISOR_TOKEN (necessario per l'API di Home Assistant).
exec python3 -m mqtt_bridge
