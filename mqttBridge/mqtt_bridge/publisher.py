"""Pubblicazione su MQTT (paho-mqtt 2.x) con riconnessione automatica."""

from __future__ import annotations

import logging
from collections.abc import Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        client_id: str,
        on_connected: Callable[[], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._on_connected = on_connected
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self._client.username_pw_set(username, password)
        self._client.reconnect_delay_set(min_delay=1, max_delay=120)
        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect

    def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    @property
    def connected(self) -> bool:
        return self._client.is_connected()

    def publish(self, topic: str, payload: str) -> bool:
        if not self._client.is_connected():
            _LOGGER.warning("MQTT non connesso: messaggio non inviato su %s", topic)
            return False
        # Con log_level debug il log mostra ogni pacchetto inviato per intero
        _LOGGER.debug("MQTT → %s %s", topic, payload)
        info = self._client.publish(topic, payload)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            _LOGGER.warning("Pubblicazione su %s fallita (rc=%s)", topic, info.rc)
            return False
        return True

    def _handle_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            _LOGGER.error("Connessione MQTT rifiutata: %s", reason_code)
            return
        _LOGGER.info("Connesso al broker MQTT %s:%s", self._host, self._port)
        if self._on_connected:
            self._on_connected()

    def _handle_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            _LOGGER.warning("MQTT disconnesso (%s), riconnessione automatica", reason_code)
