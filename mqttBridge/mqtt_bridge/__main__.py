"""Avvio dell'add-on: `python3 -m mqtt_bridge`."""

from __future__ import annotations

import asyncio
import logging
import signal

from .bridge import Bridge
from .config import load_settings
from .ha_client import HomeAssistantClient
from .publisher import MqttPublisher

_LOGGER = logging.getLogger("mqtt_bridge")


async def main() -> None:
    settings = load_settings()
    logging.getLogger().setLevel(settings.log_level.upper())
    _LOGGER.info("Avvio: %r", settings)

    ha = HomeAssistantClient(settings.ha_url, settings.supervisor_token)
    bridge: Bridge
    mqtt = MqttPublisher(
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_username,
        settings.mqtt_password,
        client_id=f"ha-mqtt-bridge-{settings.smartgate_serial.replace(':', '')}",
        # Come l'integrazione: un heartbeat appena connessi al broker
        on_connected=lambda: bridge.send_heartbeat(),
    )
    bridge = Bridge(settings, ha, mqtt)

    mqtt.start()
    tasks = [asyncio.create_task(bridge.run()), asyncio.create_task(bridge.heartbeat_loop())]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    _LOGGER.info("Arresto")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await ha.close()
    mqtt.stop()


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(levelname)s [%(name)s] %(message)s", level=logging.INFO)
    asyncio.run(main())
