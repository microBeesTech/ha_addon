"""La lettura dal socket non aspetta mai le callback degli eventi.

Log del 2026-10-28: callback bloccate fino al TimeoutError e disconnessioni da Home Assistant.
"""

import asyncio
import json

import pytest

from mqtt_bridge.ha_client import HomeAssistantClient


class FakeSocket:
    """Socket finto: i messaggi da Home Assistant si accodano con `push`, le risposte ai comandi le dà `reply`."""

    def __init__(self, reply):
        self._incoming: asyncio.Queue = asyncio.Queue()
        self._reply = reply
        self.sent = []

    def push(self, msg):
        self._incoming.put_nowait(json.dumps(msg) if msg is not None else None)

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        for answer in self._reply(msg):
            self.push(answer)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self._incoming.get()
        if raw is None:
            raise StopAsyncIteration
        return raw


def _client(socket):
    client = HomeAssistantClient("ws://supervisor/core/websocket", "t")
    client._ws = socket
    return client


def _ok(msg, result=None):
    return {"id": msg["id"], "type": "result", "success": True, "result": result}


def test_eventCallback_canSendACommandAndGetItsResult():
    async def scenario():
        devices = [{"id": "d1"}]
        socket = FakeSocket(lambda msg: [_ok(msg, devices if msg["type"] == "config/device_registry/list" else None)])
        client = _client(socket)
        received = asyncio.get_running_loop().create_future()

        async def on_event(event):
            received.set_result(await client.command({"type": "config/device_registry/list"}, timeout=2))

        reader = asyncio.create_task(client.run_forever())
        await client.subscribe("device_registry_updated", on_event)
        socket.push({"id": 1, "type": "event", "event": {"event_type": "device_registry_updated"}})

        assert await asyncio.wait_for(received, 2) == [{"id": "d1"}]
        socket.push(None)
        await reader

    asyncio.run(scenario())


def test_eventsAreHandledInOrder_andAFailingOneDoesNotStopTheOthers():
    async def scenario():
        socket = FakeSocket(lambda msg: [_ok(msg)])
        client = _client(socket)
        handled = []
        done = asyncio.Event()

        async def on_event(event):
            if event["n"] == 2:
                raise ValueError("boom")
            handled.append(event["n"])
            if event["n"] == 3:
                done.set()

        reader = asyncio.create_task(client.run_forever())
        await client.subscribe("state_changed", on_event)
        for n in (1, 2, 3):
            socket.push({"id": 1, "type": "event", "event": {"event_type": "state_changed", "n": n}})

        await asyncio.wait_for(done.wait(), 2)
        assert handled == [1, 3]
        socket.push(None)
        await reader

    asyncio.run(scenario())


def test_timedOutCommand_isNotLeftPending():
    async def scenario():
        socket = FakeSocket(lambda msg: [])
        client = _client(socket)

        with pytest.raises(TimeoutError):
            await client.command({"type": "get_states"}, timeout=0.01)
        assert client._pending == {}

    asyncio.run(scenario())
