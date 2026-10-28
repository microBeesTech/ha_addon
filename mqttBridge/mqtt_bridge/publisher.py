"""Pubblicazione su MQTT (paho-mqtt 2.x) con riconnessione automatica e ricezione dei comandi."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

DEFAULT_VHOST = "/ (predefinito del broker)"


def rabbitmq_vhost(username: str | None) -> str:
    """Vhost che il plugin MQTT di RabbitMQ ricava dal nome utente `vhost:utente` (senza prefisso: il predefinito)."""
    if username and ":" in username:
        return username.split(":", 1)[0]
    return DEFAULT_VHOST


def amqp_routing_key(topic: str) -> str:
    """Routing key AMQP di un topic MQTT: RabbitMQ scambia `/` e `.` (`ha/in` → `ha.in`, `ha.in` → `ha/in`)."""
    return topic.translate(str.maketrans("/.", "./"))


def subscription_queue(client_id: str, qos: int = 0) -> str:
    """Nome della coda che RabbitMQ crea per le iscrizioni di un client MQTT."""
    return f"mqtt-subscription-{client_id}qos{qos}"


class MqttPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        client_id: str,
        on_connected: Callable[[], None] | None = None,
        command_topic: str | None = None,
        on_command: Callable[[bytes], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._client_id = client_id
        self._subscriptions: dict[int, str] = {}  # mid -> topic, per il log dell'esito
        self._published_topics: set[str] = set()
        self._on_connected = on_connected
        self._command_topic = command_topic
        self._on_command = on_command
        self._connected = threading.Event()  # impostato dal thread di paho, letto dall'asyncio del bridge
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self._client.username_pw_set(username, password)
        self._client.reconnect_delay_set(min_delay=1, max_delay=120)
        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_message = self._handle_message
        self._client.on_subscribe = self._handle_subscribe

    def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    @property
    def connected(self) -> bool:
        return self._client.is_connected()

    async def wait_connected(self) -> None:
        """Attende la prima connessione (o la riconnessione) al broker."""
        if not self._connected.is_set():
            _LOGGER.info("In attesa del broker MQTT %s:%s", self._host, self._port)
            await asyncio.to_thread(self._connected.wait)

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
        if topic not in self._published_topics:
            self._published_topics.add(topic)
            _LOGGER.info(
                "Primo messaggio pubblicato su %s: routing key AMQP %s sull'exchange MQTT del broker, vhost %s",
                topic,
                amqp_routing_key(topic),
                rabbitmq_vhost(self._username),
            )
        return True

    def _handle_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            _LOGGER.error(
                "Connessione MQTT rifiutata: %s (utente %s, vhost %s, client_id %s): controllare utente nel formato "
                "vhost:utente, password e permessi dell'utente sul vhost",
                reason_code,
                self._username,
                rabbitmq_vhost(self._username),
                self._client_id,
            )
            return
        _LOGGER.info(
            "Connesso al broker MQTT %s:%s: utente %s, vhost %s, client_id %s, sessione già presente %s",
            self._host,
            self._port,
            self._username,
            rabbitmq_vhost(self._username),
            self._client_id,
            getattr(flags, "session_present", None),
        )
        self._connected.set()
        if self._command_topic:
            # A ogni connessione: la sottoscrizione non sopravvive a una sessione nuova del broker
            result, mid = client.subscribe(self._command_topic, qos=0)
            self._subscriptions[mid] = self._command_topic
            _LOGGER.info(
                "Iscrizione ai comandi su %s (rc=%s): routing key AMQP %s, coda RabbitMQ %s nel vhost %s, legata "
                "all'exchange MQTT del broker (mqtt.exchange, predefinita amq.topic)",
                self._command_topic,
                result,
                amqp_routing_key(self._command_topic),
                subscription_queue(self._client_id),
                rabbitmq_vhost(self._username),
            )
        if self._on_connected:
            self._on_connected()

    def _handle_subscribe(self, client, userdata, mid, reason_code_list, properties) -> None:
        topic = self._subscriptions.pop(mid, None)
        for rc in reason_code_list:
            if getattr(rc, "is_failure", False):
                _LOGGER.error("Iscrizione a %s rifiutata dal broker: %s (permessi di lettura dell'utente)", topic, rc)
            else:
                _LOGGER.info("Iscrizione a %s confermata dal broker: %s", topic, rc)

    def _handle_message(self, client, userdata, message) -> None:
        _LOGGER.debug("MQTT ← %s %s", message.topic, message.payload.decode("utf-8", errors="replace"))
        if self._on_command:
            self._on_command(message.payload)

    def _handle_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self._connected.clear()
        if reason_code != 0:
            _LOGGER.warning("MQTT disconnesso (%s), riconnessione automatica", reason_code)
