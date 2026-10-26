"""Client minimo dell'API WebSocket di Home Assistant (via Supervisor).

Comandi con risposta (`command`) ed eventi in abbonamento (`subscribe`). Un solo task legge
dal socket e smista risultati ed eventi; se la connessione cade, `run_forever` termina e chi
chiama riconnette.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

_LOGGER = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class HomeAssistantError(Exception):
    pass


class HomeAssistantClient:
    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self._ws: Any = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._subscriptions: dict[int, EventCallback] = {}

    async def connect(self) -> None:
        # max_size: i registri di un'installazione grande superano il limite di default (1 MiB)
        self._ws = await websockets.connect(self._url, max_size=64 * 1024 * 1024)
        hello = json.loads(await self._ws.recv())
        if hello.get("type") != "auth_required":
            raise HomeAssistantError(f"risposta inattesa: {hello.get('type')}")
        await self._ws.send(json.dumps({"type": "auth", "access_token": self._token}))
        auth = json.loads(await self._ws.recv())
        if auth.get("type") != "auth_ok":
            raise HomeAssistantError("autenticazione su Home Assistant fallita")
        self._ids = itertools.count(1)
        self._pending.clear()
        self._subscriptions.clear()
        _LOGGER.info("Connesso a Home Assistant %s", auth.get("ha_version", ""))

    async def run_forever(self) -> None:
        """Legge finché la connessione resta aperta; alla chiusura fallisce le richieste in attesa."""
        try:
            async for raw in self._ws:
                await self._dispatch(json.loads(raw))
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("connessione con Home Assistant chiusa"))
            self._pending.clear()

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def command(self, message: dict[str, Any], timeout: float = 60) -> Any:
        msg_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        await self._ws.send(json.dumps({"id": msg_id, **message}))
        return await asyncio.wait_for(future, timeout)

    async def subscribe(self, event_type: str, callback: EventCallback) -> None:
        msg_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        self._subscriptions[msg_id] = callback
        await self._ws.send(json.dumps({"id": msg_id, "type": "subscribe_events", "event_type": event_type}))
        await asyncio.wait_for(future, 30)

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        if msg.get("type") == "result":
            future = self._pending.pop(msg["id"], None)
            if future is None or future.done():
                return
            if msg.get("success"):
                future.set_result(msg.get("result"))
            else:
                error = msg.get("error") or {}
                future.set_exception(HomeAssistantError(f"{error.get('code')}: {error.get('message')}"))
        elif msg.get("type") == "event":
            callback = self._subscriptions.get(msg["id"])
            if callback is not None:
                # Un errore su un evento non deve fermare la lettura degli altri
                try:
                    await callback(msg["event"])
                except Exception:
                    _LOGGER.exception("Errore nella gestione di un evento %s", msg["event"].get("event_type"))
