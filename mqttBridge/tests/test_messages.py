"""I pacchetti contengono i dati di Home Assistant così come sono: nessun valore ricavato o convertito."""

import json

from mqtt_bridge import messages

SERIAL = "30:ae:7b:ea:86:80"


def test_new_device_porta_dispositivo_ed_entita_senza_modifiche(zha_message, zha_inputs):
    device, entities, states = zha_inputs

    out = json.loads(messages.device_snapshot(device, entities, states, SERIAL))

    assert out["message_type"] == "new_device" and out["smartgate_serial"] == SERIAL and "timestamp" in out
    assert {k: out[k] for k in device} == device  # dispositivo identico al registro
    for got, entity in zip(out["entities"], entities, strict=True):
        state_obj = got.pop("state_obj")
        assert got == entity  # entità identica al registro, niente campi calcolati
        assert state_obj == states.get(entity["entity_id"])  # stato grezzo di HA (o null)


def test_new_device_stesso_dispositivo_ed_entita_dell_integrazione(zha_message, zha_inputs):
    """Rispetto al messaggio reale dell'integrazione mancano solo i campi che lei calcolava."""
    device, entities, states = zha_inputs
    out = json.loads(messages.device_snapshot(device, entities, states, SERIAL))

    calcolati = {"available", "domain", "state_obj"}
    for got, expected in zip(out["entities"], zha_message["entities"], strict=True):
        assert {k: v for k, v in got.items() if k not in calcolati} == {
            k: v for k, v in expected.items() if k not in calcolati
        }


def test_evento_di_registro_inoltrato_com_e():
    event = {"event_type": "device_registry_updated", "data": {"action": "update", "device_id": "d1", "changes": {}}}
    device = {"id": "d1", "name": "x"}

    out = json.loads(messages.registry_event(event, device, "device", SERIAL))

    assert out["message_type"] == "device_registry_updated"
    assert out["event"] == event and out["device"] == device


def test_cambio_di_stato_inoltrato_com_e():
    event = {
        "event_type": "state_changed",
        "data": {"entity_id": "switch.luce", "old_state": {"state": "on"}, "new_state": {"state": "off"}},
        "origin": "LOCAL",
        "time_fired": "2026-10-26T08:33:37+00:00",
        "context": {"id": "c"},
    }

    out = json.loads(messages.state_event(event, SERIAL))

    assert out["message_type"] == "state_changed" and out["event"] == event
    assert set(out) == {"message_type", "smartgate_serial", "timestamp", "event"}


def test_heartbeat():
    out = json.loads(messages.heartbeat(SERIAL))
    assert out["message_type"] == "smartgate_heartbeat" and out["smartgate_serial"] == SERIAL
