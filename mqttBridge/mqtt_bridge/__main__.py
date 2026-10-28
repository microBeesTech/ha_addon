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


def apply_log_level(level: str) -> None:
    """`off` = nessun log; altrimenti la soglia scelta (`debug` mostra anche ogni JSON inviato per intero)."""
    logging.disable(logging.CRITICAL if level == "off" else logging.NOTSET)
    logging.getLogger().setLevel(logging.CRITICAL if level == "off" else level.upper())
    # Le librerie in debug stampano frame troncati e ping: al massimo INFO, il debug è solo per i nostri messaggi
    logging.getLogger("websockets").setLevel(logging.INFO)
    logging.getLogger("paho").setLevel(logging.INFO)


async def main() -> None:
    settings = load_settings()
    apply_log_level(settings.log_level)
    _LOGGER.info("Avvio: %r", settings)

    ha = HomeAssistantClient(settings.ha_url, settings.supervisor_token)
    loop = asyncio.get_running_loop()
    bridge: Bridge
    first_connection = True

    def on_mqtt_connected() -> None:
        # Gira nel thread di paho. Heartbeat appena connessi; dalla seconda connessione in poi
        # (broker caduto e tornato) si rifà anche l'invio iniziale.
        nonlocal first_connection
        bridge.send_heartbeat()
        if not first_connection:
            asyncio.run_coroutine_threadsafe(bridge.resync(), loop)
        first_connection = False

    mqtt = MqttPublisher(
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_username,
        settings.mqtt_password,
        client_id=f"ha-mqtt-bridge-{settings.smartgate_serial.replace(':', '')}",
        on_connected=on_mqtt_connected,
        command_topic=settings.command_topic,
        # Gira nel thread di paho: il comando si esegue nel loop asyncio, dove vive la connessione a Home Assistant
        on_command=lambda payload: asyncio.run_coroutine_threadsafe(bridge.handle_command(payload), loop),
    )
    bridge = Bridge(settings, ha, mqtt)

    mqtt.start()
    tasks = [asyncio.create_task(bridge.run()), asyncio.create_task(bridge.heartbeat_loop())]

    stop = asyncio.Event()
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
