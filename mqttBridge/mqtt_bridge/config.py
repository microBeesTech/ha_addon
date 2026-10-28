"""Opzioni dell'add-on (scritte dal Supervisor in /data/options.json) e serial del gateway."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

OPTIONS_FILE = Path("/data/options.json")
HA_WEBSOCKET_URL = "ws://supervisor/core/websocket"


@dataclass(frozen=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    topic: str
    command_topic: str
    smartgate_serial: str
    heartbeat_interval: int
    send_device_status: bool
    log_level: str
    supervisor_token: str
    addon_version: str = "dev"
    ha_url: str = HA_WEBSOCKET_URL

    def __repr__(self) -> str:  # niente password né token nei log
        return (
            f"Settings(mqtt={self.mqtt_host}:{self.mqtt_port}, topic={self.topic}, "
            f"commands={self.command_topic}, serial={self.smartgate_serial})"
        )


def host_mac() -> str:
    """MAC dell'host nel formato `aa:bb:cc:dd:ee:ff`.

    Con `host_network: true` l'add-on vede le stesse interfacce del core di Home Assistant,
    quindi `uuid.getnode()` dà il MAC dell'host e non quello del container.
    """
    mac = uuid.getnode()
    if (mac >> 40) & 1:
        _LOGGER.warning(
            "MAC dell'host non leggibile: uuid.getnode() ha restituito un valore casuale. "
            "Imposta smartgate_serial nella configurazione."
        )
    return ":".join(f"{(mac >> ele) & 0xFF:02x}" for ele in range(40, -1, -8))


def default_command_topic(serial: str) -> str:
    """Topic dei comandi se non configurato: uno per gateway, `ha/cmd/<serial>` (con i due punti, minuscolo).

    RabbitMQ converte `/` in `.`: è la routing key `ha.cmd.<serial>` con cui il Cloud manda i comandi.
    """
    return f"ha/cmd/{serial}"


def load_settings(path: Path = OPTIONS_FILE, env: dict[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    options = json.loads(path.read_text(encoding="utf-8"))

    token = env.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError(
            "SUPERVISOR_TOKEN mancante: serve homeassistant_api: true in config.yaml e l'avvio da run.sh (with-contenv)"
        )
    if not options.get("mqtt_host"):
        raise RuntimeError("mqtt_host non configurato nelle opzioni dell'add-on")

    serial = (options.get("smartgate_serial") or "").strip().lower() or host_mac()

    return Settings(
        mqtt_host=options["mqtt_host"],
        mqtt_port=int(options.get("mqtt_port", 1883)),
        mqtt_username=options.get("mqtt_username") or None,
        mqtt_password=options.get("mqtt_password") or None,
        topic=options.get("topic") or "ha.in",
        command_topic=(options.get("command_topic") or "").strip() or default_command_topic(serial),
        smartgate_serial=serial,
        heartbeat_interval=int(options.get("heartbeat_interval", 300)),
        send_device_status=bool(options.get("send_device_status", True)),
        log_level=str(options.get("log_level", "info")),
        supervisor_token=token,
        # BUILD_VERSION (= version di config.yaml) passato dal Supervisor alla build, vedi Dockerfile
        addon_version=env.get("ADDON_VERSION") or "dev",
    )
