import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def zha_message() -> dict:
    """Messaggio new_device reale (log del 2026-10-26)."""
    return json.loads((FIXTURES / "new_device_zha.json").read_text(encoding="utf-8"))


@pytest.fixture
def zha_inputs(zha_message):
    """Ricostruisce dal messaggio reale i dati come li restituisce l'API WebSocket di Home Assistant."""
    added = {"state_obj", "available", "domain"}
    device = {k: v for k, v in zha_message.items() if k not in ("message_type", "smartgate_serial", "entities")}
    entities = [{k: v for k, v in e.items() if k not in added} for e in zha_message["entities"]]
    states = {}
    for e in zha_message["entities"]:
        if e["state_obj"]:
            s = json.loads(e["state_obj"])
            states[s["entity_id"]] = {
                "entity_id": s["entity_id"],
                "state": s["state"],
                "attributes": s["attributes"],
                "last_changed": s["last_changed"],
                "last_reported": s["last_reported"],
                "last_updated": s["last_updated"],
                "context": {"id": s["context"]["id"], "parent_id": None, "user_id": None},
            }
    return device, entities, states
