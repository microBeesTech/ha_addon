"""Log di connessione e conversioni topic MQTT ↔ routing key AMQP di RabbitMQ."""

import logging
from types import SimpleNamespace

from mqtt_bridge.publisher import MqttPublisher, amqp_routing_key, rabbitmq_vhost, subscription_queue


def test_routing_key_scambia_barre_e_punti():
    assert amqp_routing_key("ha/in") == "ha.in"
    assert amqp_routing_key("ha.in") == "ha/in"  # il punto diventa barra: non arriva al Cloud
    assert amqp_routing_key("ha/cmd/30:ae:7b:ea:86:80") == "ha.cmd.30:ae:7b:ea:86:80"


def test_vhost_dal_nome_utente():
    assert rabbitmq_vhost("beessmart:homeassistant") == "beessmart"
    assert rabbitmq_vhost("homeassistant").startswith("/")
    assert rabbitmq_vhost(None).startswith("/")


def test_coda_delle_iscrizioni():
    assert subscription_queue("ha-mqtt-bridge-30ae7bea8680") == "mqtt-subscription-ha-mqtt-bridge-30ae7bea8680qos0"


class FakeClient:
    def __init__(self):
        self.subscribed = []

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)
        return 0, 7


def _publisher():
    return MqttPublisher(
        "test.microbees.com",
        1883,
        "beessmart:homeassistant",
        "segreta",
        client_id="ha-mqtt-bridge-x",
        command_topic="ha/cmd/aa:bb",
    )


def test_connessione_e_iscrizione_nel_log_senza_password(caplog):
    p = _publisher()
    caplog.set_level(logging.INFO)

    p._handle_connect(
        FakeClient(), None, SimpleNamespace(session_present=False), SimpleNamespace(is_failure=False), None
    )
    p._handle_subscribe(None, None, 7, [SimpleNamespace(is_failure=False)], None)

    text = caplog.text
    assert "utente beessmart:homeassistant, vhost beessmart, client_id ha-mqtt-bridge-x" in text
    assert "routing key AMQP ha.cmd.aa:bb" in text and "mqtt-subscription-ha-mqtt-bridge-xqos0" in text
    assert "Iscrizione a ha/cmd/aa:bb confermata" in text
    assert "segreta" not in text


def test_connessione_rifiutata_nel_log_con_utente_e_vhost(caplog):
    p = _publisher()

    p._handle_connect(
        FakeClient(), None, None, SimpleNamespace(is_failure=True, __str__=lambda s: "Not authorized"), None
    )

    assert "rifiutata" in caplog.text and "vhost beessmart" in caplog.text and "segreta" not in caplog.text


def test_iscrizione_rifiutata_nel_log(caplog):
    p = _publisher()
    p._subscriptions[3] = "ha/cmd/aa:bb"

    p._handle_subscribe(None, None, 3, [SimpleNamespace(is_failure=True)], None)

    assert "Iscrizione a ha/cmd/aa:bb rifiutata" in caplog.text
