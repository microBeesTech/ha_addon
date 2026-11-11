"""Avvio dell'add-on: `python3 -m mqtt_bridge`."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from pathlib import Path

from .bridge import Bridge
from .config import Settings, load_settings
from .ha_client import HomeAssistantClient
from .identity import IdentityError, IdentityStore, reset_identity_files
from .provisioning import ProvisioningError, run_provisioning
from .publisher import MqttPublisher

_LOGGER = logging.getLogger("mqtt_bridge")
IDENTITY_RESET_MARKER = Path("/data/provisioning-reset.applied")


def apply_identity_reset(settings: Settings) -> None:
    """Reset una-tantum dell'identita', senza toccare /data/options.json.

    Il marker evita di cancellare l'identita' a ogni riavvio se l'opzione
    provisioning_reset_identity resta true. Va riportata a false dopo il reset.
    """

    marker = IDENTITY_RESET_MARKER
    if settings.provisioning_reset_identity:
        if marker.exists():
            _LOGGER.warning(
                "Reset identita' gia' applicato: imposta provisioning_reset_identity=false "
                "prima di richiederne un altro"
            )
            return
        removed = reset_identity_files(settings.provisioning_state_dir)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("applied\n", encoding="utf-8")
        _LOGGER.warning(
            "Reset identita' richiesto: file rimossi=%s; verra' creata una nuova identita'",
            removed,
        )
    else:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass


def apply_log_level(level: str) -> None:
    """`off` = nessun log; altrimenti la soglia scelta (`debug` mostra anche ogni JSON inviato per intero)."""
    logging.disable(logging.CRITICAL if level == "off" else logging.NOTSET)
    logging.getLogger().setLevel(logging.CRITICAL if level == "off" else level.upper())
    # Le librerie in debug stampano frame troncati e ping: al massimo INFO, il debug è solo per i nostri messaggi
    logging.getLogger("websockets").setLevel(logging.INFO)
    logging.getLogger("paho").setLevel(logging.INFO)


def provision_identity(settings: Settings) -> IdentityStore:
    """Identita' persistente, CSR e attesa del certificato; nessun fallback a password."""

    try:
        store = IdentityStore(
            settings.provisioning_state_dir,
            settings.smartgate_serial,
            settings.addon_version,
            common_name=settings.provisioning_common_name,
            trusted_ca_file=Path(settings.provisioning_ca_file) if settings.provisioning_ca_file else None,
        )
        run_provisioning(settings, store)
        return store
    except (IdentityError, ProvisioningError) as err:
        _LOGGER.error("Provisioning non completato: %s. Nessuna rigenerazione automatica.", err)
        raise SystemExit(1) from err


def mqtt_client_id(settings: Settings) -> str:
    return f"ha-mqtt-bridge-{settings.smartgate_serial.replace(':', '')}"


async def run_bridge(
    settings: Settings,
    mqtt_factory: Callable[[Callable[[], None], Callable[[bytes], None]], MqttPublisher],
) -> None:
    """Avvia il bridge con il publisher scelto (password manuale o mTLS provisioned)."""

    ha = HomeAssistantClient(settings.ha_url, settings.supervisor_token)
    loop = asyncio.get_running_loop()
    bridge: Bridge | None = None
    first_connection = True

    def on_mqtt_connected() -> None:
        # Gira nel thread di paho. Heartbeat appena connessi; dalla seconda connessione in poi
        # (broker caduto e tornato) si rifà anche l'invio iniziale.
        nonlocal first_connection
        if bridge is None:
            return
        bridge.send_heartbeat()
        if not first_connection:
            asyncio.run_coroutine_threadsafe(bridge.resync(), loop)
        first_connection = False

    def on_command(payload: bytes) -> None:
        # Gira nel thread di paho: il comando si esegue nel loop asyncio, dove vive HA.
        if bridge is not None:
            asyncio.run_coroutine_threadsafe(bridge.handle_command(payload), loop)

    mqtt = mqtt_factory(on_mqtt_connected, on_command)
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


async def main() -> None:
    settings = load_settings()
    apply_log_level(settings.log_level)
    _LOGGER.info("Avvio: %r", settings)

    if settings.provisioning_mode == "provisioned":
        apply_identity_reset(settings)
        store = provision_identity(settings)

        def provisioned_mqtt(
            on_connected: Callable[[], None], on_command: Callable[[bytes], None]
        ) -> MqttPublisher:
            return MqttPublisher(
                settings.mqtt_host,
                settings.mqtt_tls_port,
                None,
                None,
                client_id=mqtt_client_id(settings),
                on_connected=on_connected,
                command_topic=settings.command_topic,
                on_command=on_command,
                tls=True,
                tls_ca_certs=settings.mqtt_tls_ca_file,
                tls_certfile=str(store.certificate_path),
                tls_keyfile=str(store.key_path),
                vhost_label="beessmart (porta 8884)",
            )

        await run_bridge(settings, provisioned_mqtt)
        return

    def manual_mqtt(
        on_connected: Callable[[], None], on_command: Callable[[bytes], None]
    ) -> MqttPublisher:
        return MqttPublisher(
            settings.mqtt_host,
            settings.mqtt_port,
            settings.mqtt_username,
            settings.mqtt_password,
            client_id=mqtt_client_id(settings),
            on_connected=on_connected,
            command_topic=settings.command_topic,
            on_command=on_command,
        )

    await run_bridge(settings, manual_mqtt)


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(levelname)s [%(name)s] %(message)s", level=logging.INFO)
    asyncio.run(main())
