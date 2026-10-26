"""Il bridge inoltra ogni evento così com'è, senza filtri."""

import asyncio
import json

from mqtt_bridge.bridge import Bridge
from mqtt_bridge.config import Settings

SETTINGS = Settings("h", 1883, None, None, "mio/topic", "30:ae:7b:ea:86:80", 300, True, "info", "t")
HELPER = {"entity_id": "input_boolean.vacanza", "device_id": None}


class FakeHA:
    def __init__(self, devices, entities, states):
        self.devices, self.entities, self.states = devices, {e["entity_id"]: e for e in entities}, states

    async def command(self, msg):
        kind = msg["type"]
        if kind == "config/device_registry/list":
            return self.devices
        if kind == "config/entity_registry/list":
            return [{"entity_id": eid} for eid in self.entities]
        if kind == "config/entity_registry/get_entries":
            return {eid: self.entities.get(eid) for eid in msg["entity_ids"]}
        if kind == "get_states":
            return list(self.states.values())
        raise AssertionError(kind)


class FakeMqtt:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload):
        self.sent.append((topic, json.loads(payload)))
        return True


def _make(zha_inputs, extra_devices=(), extra_entities=()):
    device, entities, states = zha_inputs
    ha, mqtt = FakeHA([device, *extra_devices], [*entities, *extra_entities], states), FakeMqtt()
    return Bridge(SETTINGS, ha, mqtt), ha, mqtt


def _state(entity_id):
    return {
        "event_type": "state_changed",
        "data": {"entity_id": entity_id, "old_state": None, "new_state": {"state": "on"}},
    }


def test_invio_iniziale_un_messaggio_per_ogni_dispositivo_sul_topic_della_config(zha_inputs):
    empty = {**zha_inputs[0], "id": "senza-entita"}
    bridge, _, mqtt = _make(zha_inputs, [empty], [HELPER])

    asyncio.run(bridge.full_sync())

    assert {t for t, _ in mqtt.sent} == {"mio/topic"}
    assert [m["message_type"] for _, m in mqtt.sent] == ["new_device", "new_device", "new_entity"]
    assert [len(m["entities"]) for _, m in mqtt.sent[:2]] == [7, 0]  # anche senza entità: nessun filtro
    assert mqtt.sent[2][1]["entity_id"] == "input_boolean.vacanza" and mqtt.sent[2][1]["state_obj"] is None


def test_ogni_evento_di_stato_diventa_un_messaggio(zha_inputs):
    bridge, _, mqtt = _make(zha_inputs, extra_entities=[HELPER])

    async def scenario():
        await bridge.full_sync()
        mqtt.sent.clear()
        await bridge._on_state_changed(_state("sensor.sensore_temperatura_e_umidita_temperatura"))
        await bridge._on_state_changed(_state("input_boolean.vacanza"))  # anche senza dispositivo

    asyncio.run(scenario())

    assert [m["message_type"] for _, m in mqtt.sent] == ["state_changed", "state_changed"]


def test_eventi_di_registro_inoltrati_con_l_elemento_attuale(zha_inputs):
    device, _, _ = zha_inputs
    bridge, ha, mqtt = _make(zha_inputs, extra_entities=[HELPER])
    eid = "sensor.tz3000_zl1kmjqx_rssi"

    async def scenario():
        await bridge.full_sync()
        mqtt.sent.clear()
        await bridge._on_device_registry_updated(
            {"event_type": "device_registry_updated", "data": {"action": "update", "device_id": device["id"]}}
        )
        ha.entities.pop(eid)
        await bridge._on_entity_registry_updated(
            {"event_type": "entity_registry_updated", "data": {"action": "remove", "entity_id": eid}}
        )
        await bridge._on_entity_registry_updated(
            {
                "event_type": "entity_registry_updated",
                "data": {"action": "update", "entity_id": "input_boolean.vacanza"},
            }
        )

    asyncio.run(scenario())

    kinds = [(m["message_type"], m.get("device", m.get("entity"))) for _, m in mqtt.sent]
    assert kinds[0] == ("device_registry_updated", device)
    assert kinds[1] == ("entity_registry_updated", None)  # rimossa: l'evento arriva, l'entità è null
    assert kinds[2] == ("entity_registry_updated", HELPER)  # anche senza dispositivo


def test_nuova_entita_di_un_dispositivo_poi_segue_anche_negli_stati(zha_inputs):
    bridge, ha, mqtt = _make(zha_inputs)
    new = {"entity_id": "switch.nuovo", "device_id": "d-nuovo"}

    async def scenario():
        await bridge.full_sync()
        mqtt.sent.clear()
        ha.entities[new["entity_id"]] = new
        await bridge._on_entity_registry_updated(
            {"event_type": "entity_registry_updated", "data": {"action": "create", "entity_id": "switch.nuovo"}}
        )
        await bridge._on_state_changed(_state("switch.nuovo"))

    asyncio.run(scenario())

    assert [m["message_type"] for _, m in mqtt.sent] == ["entity_registry_updated", "state_changed"]
