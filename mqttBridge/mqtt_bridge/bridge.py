"""Lettura da Home Assistant e invio su MQTT, senza logica sui dati.

1. all'avvio (e a ogni riconnessione con Home Assistant): un `new_device` per ogni dispositivo del registro e un
   `new_entity` per ogni entità senza dispositivo (helper, `sun`, `person`, automazioni…);
2. ogni evento `device_registry_updated` → il messaggio con l'evento e il dispositivo com'è ora;
3. ogni evento `entity_registry_updated` → il messaggio con l'evento e l'entità com'è ora;
4. ogni evento `state_changed` → il messaggio con l'evento (se `send_device_status` è attivo);
5. heartbeat periodico.

Nessun filtro, nessuna attesa, nessun valore ricavato: ogni evento diventa un messaggio, il consumer decide.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import messages
from .config import Settings
from .ha_client import HomeAssistantClient
from .publisher import MqttPublisher

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_MAX = 60


class Bridge:
    def __init__(self, settings: Settings, ha: HomeAssistantClient, mqtt: MqttPublisher) -> None:
        self._settings = settings
        self._ha = ha
        self._mqtt = mqtt

    # ------------------------------------------------------------------ ciclo principale ---

    async def run(self) -> None:
        delay = 1
        while True:
            reader: asyncio.Task | None = None
            try:
                await self._ha.connect()
                reader = asyncio.create_task(self._ha.run_forever())
                await self._ha.subscribe("device_registry_updated", self._on_device_registry_updated)
                await self._ha.subscribe("entity_registry_updated", self._on_entity_registry_updated)
                if self._settings.send_device_status:
                    await self._ha.subscribe("state_changed", self._on_state_changed)
                await self.full_sync()
                delay = 1
                await reader
                _LOGGER.warning("Connessione con Home Assistant chiusa, riconnessione")
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning("Home Assistant non raggiungibile (%s), nuovo tentativo tra %ss", err, delay)
            finally:
                if reader is not None and not reader.done():
                    reader.cancel()
                await self._ha.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_DELAY_MAX)

    async def heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._settings.heartbeat_interval)
            self.send_heartbeat()

    def send_heartbeat(self) -> None:
        self._publish(messages.heartbeat(self._settings.smartgate_serial))

    # ---------------------------------------------------------------------- invio iniziale ---

    async def full_sync(self) -> None:
        devices = await self._ha.command({"type": "config/device_registry/list"})
        registry = await self._ha.command({"type": "config/entity_registry/list"})
        entities = await self._entities([e["entity_id"] for e in registry])
        states = {s["entity_id"]: s for s in await self._ha.command({"type": "get_states"})}

        by_device: dict[str, list[dict[str, Any]]] = {}
        for entity in entities.values():
            by_device.setdefault(entity.get("device_id"), []).append(entity)

        for device in devices:
            self._publish(
                messages.device_snapshot(
                    device, by_device.get(device["id"], []), states, self._settings.smartgate_serial
                )
            )
        for entity in by_device.get(None, []):
            self._publish(messages.entity_snapshot(entity, states, self._settings.smartgate_serial))
        _LOGGER.info("Invio iniziale: %s dispositivi, %s entità", len(devices), len(entities))

    # ------------------------------------------------------------------------------ eventi ---

    async def _on_device_registry_updated(self, event: dict[str, Any]) -> None:
        device_id = (event.get("data") or {}).get("device_id")
        devices = await self._ha.command({"type": "config/device_registry/list"})
        device = next((d for d in devices if d["id"] == device_id), None)
        self._publish(messages.registry_event(event, device, "device", self._settings.smartgate_serial))

    async def _on_entity_registry_updated(self, event: dict[str, Any]) -> None:
        entity_id = (event.get("data") or {}).get("entity_id")
        entity = (await self._entities([entity_id])).get(entity_id)
        self._publish(messages.registry_event(event, entity, "entity", self._settings.smartgate_serial))

    async def _on_state_changed(self, event: dict[str, Any]) -> None:
        self._publish(messages.state_event(event, self._settings.smartgate_serial))

    # ---------------------------------------------------------------------------- helper ---

    def _publish(self, payload: str) -> None:
        self._mqtt.publish(self._settings.topic, payload)

    async def _entities(self, entity_ids: list[str]) -> dict[str, dict[str, Any] | None]:
        result = await self._ha.command({"type": "config/entity_registry/get_entries", "entity_ids": entity_ids})
        return result or {}
