"""Pacchetti JSON in uscita: i dati di Home Assistant così come arrivano, senza calcoli né decisioni.

Ogni funzione aggiunge solo `message_type`, `smartgate_serial` e `timestamp` e mette i dati di Home Assistant in
chiavi fisse. Nessun valore viene ricavato, convertito o filtrato: lo fa il consumer.

Fonti (API WebSocket di Home Assistant):
- dispositivo = `config/device_registry/list`        → `DeviceEntry.dict_repr`
- entità      = `config/entity_registry/get_entries` → `RegistryEntry.extended_dict`
- stato       = `get_states` / evento `state_changed` → `State.as_dict()`
- eventi      = `device_registry_updated`, `entity_registry_updated`, `state_changed` (evento completo)
- comandi     = busta `{"nonce", "command", "version", "params"}`: `resync` → di nuovo l'invio iniziale,
                `call_service` → `call_service` con `params` = `{domain, service, target, data}`
"""

from __future__ import annotations

import json
import time
from typing import Any


def now_ms() -> int:
    return int(time.time() * 1000)


def device_snapshot(
    device: dict[str, Any],
    entities: list[dict[str, Any]],
    states: dict[str, dict[str, Any]],
    smartgate_serial: str,
) -> str:
    """`new_device`: il dispositivo, le sue entità e per ciascuna lo stato attuale (`state_obj`, null se assente)."""
    return json.dumps(
        {
            **device,
            "message_type": "new_device",
            "smartgate_serial": smartgate_serial,
            "timestamp": now_ms(),
            "entities": [{**entity, "state_obj": states.get(entity["entity_id"])} for entity in entities],
        }
    )


def entity_snapshot(entity: dict[str, Any], states: dict[str, dict[str, Any]], smartgate_serial: str) -> str:
    """`new_entity`: un'entità senza dispositivo e il suo stato attuale (`state_obj`, null se assente)."""
    return json.dumps(
        {
            **entity,
            "message_type": "new_entity",
            "smartgate_serial": smartgate_serial,
            "timestamp": now_ms(),
            "state_obj": states.get(entity["entity_id"]),
        }
    )


def registry_event(event: dict[str, Any], item: dict[str, Any] | None, item_key: str, smartgate_serial: str) -> str:
    """`device_registry_updated` / `entity_registry_updated`: l'evento di Home Assistant così com'è e l'elemento
    del registro com'è ora (`device` o `entity`; null se è stato rimosso)."""
    return json.dumps(
        {
            "message_type": event.get("event_type"),
            "smartgate_serial": smartgate_serial,
            "timestamp": now_ms(),
            "event": event,
            item_key: item,
        }
    )


def state_event(event: dict[str, Any], smartgate_serial: str) -> str:
    """`state_changed`: l'evento di Home Assistant così com'è (old_state e new_state completi)."""
    return json.dumps(
        {
            "message_type": event.get("event_type"),
            "smartgate_serial": smartgate_serial,
            "timestamp": now_ms(),
            "event": event,
        }
    )


def heartbeat(smartgate_serial: str, addon_version: str) -> str:
    """`smartgate_heartbeat`: il gateway è vivo, con la versione dell'add-on."""
    return json.dumps(
        {
            "message_type": "smartgate_heartbeat",
            "smartgate_serial": smartgate_serial,
            "timestamp": now_ms(),
            "addon_version": addon_version,
        }
    )


def command_name(command: Any) -> Any:
    """Nome del comando nella busta (`nonce` e `version` per ora non servono). Senza `command` è il formato 0.2.0,
    cioè direttamente `{domain, service, target, data}`: una chiamata di servizio."""
    if not isinstance(command, dict):
        raise ValueError("il comando deve essere un oggetto JSON")
    return command.get("command", "call_service")


def service_call(command: dict[str, Any]) -> dict[str, Any]:
    """Comando `call_service` (`params` della busta, o il comando stesso nel formato 0.2.0) → messaggio
    `call_service` dell'API WebSocket.

    I campi passano così come sono (`data` diventa `service_data`): la validazione la fa Home Assistant.
    """
    params = command.get("params") if "command" in command else command
    if not isinstance(params, dict):
        raise ValueError("params deve essere un oggetto JSON")
    message = {
        "type": "call_service",
        "domain": params.get("domain"),
        "service": params.get("service"),
        "service_data": params.get("data") or {},
    }
    if "target" in params:
        message["target"] = params["target"]
    return message


def command_result(command: Any, result: Any, error: str | None, smartgate_serial: str) -> str:
    """`command_result`: il comando ricevuto com'è e la risposta di Home Assistant com'è (o l'errore)."""
    return json.dumps(
        {
            "message_type": "command_result",
            "smartgate_serial": smartgate_serial,
            "timestamp": now_ms(),
            "command": command,
            "success": error is None,
            "result": result,
            "error": error,
        }
    )
