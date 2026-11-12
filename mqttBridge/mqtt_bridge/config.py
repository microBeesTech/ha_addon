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
IDENTITY_STATE_DIR = Path("/data/provisioning")
PROVISIONING_MODES = ("manual", "provisioned")


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
    # "manual" mantiene il percorso 0.4.0; "provisioned" usa l'identita' persistente.
    # Nessun fallback automatico fra i due.
    provisioning_mode: str = "manual"
    provisioning_ca_file: str | None = None
    provisioning_common_name: str | None = None
    provisioning_state_dir: Path = IDENTITY_STATE_DIR
    # Bootstrap MQTT TLS: endpoint e credenziali del laboratorio, distinti dalla porta manuale.
    provisioning_bootstrap_dedicated: bool = False
    provisioning_bootstrap_host: str | None = None
    provisioning_bootstrap_username: str | None = None
    provisioning_bootstrap_password_file: str | None = None
    provisioning_bootstrap_password: str | None = None
    provisioning_bootstrap_port: int = 8883
    provisioning_bootstrap_ca_file: str | None = None
    provisioning_allow_legacy_ca: bool = False
    provisioning_request_topic: str = "ha/provisioning/requests"
    provisioning_reply_prefix: str = "ha/provisioning/replies/"
    provisioning_timeout: int = 30
    # Connessione operativa mTLS del percorso provisioned (porta 8884 in laboratorio).
    mqtt_tls_port: int = 8884
    mqtt_tls_ca_file: str | None = None
    # Fallback opzionale per la password bootstrap, senza metterla nelle opzioni o nell'immagine.
    mqtt_password_file: str | None = None
    # Reset una-tantum di /data/provisioning, senza disinstallare l'add-on.
    provisioning_reset_identity: bool = False
    led_status: bool = True

    def __repr__(self) -> str:  # niente password né token nei log
        provisioned = self.provisioning_mode == "provisioned"
        port = self.mqtt_tls_port if provisioned else self.mqtt_port
        user = "mTLS" if provisioned else self.mqtt_username
        return (
            f"Settings(mqtt={self.mqtt_host}:{port}, user={user}, user={self.mqtt_username}, topic={self.topic}, "
            f"commands={self.command_topic}, serial={self.smartgate_serial}, version={self.addon_version}, "
            f"provisioning={self.provisioning_mode}, version={self.addon_version})"
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
    mqtt_host = str(options.get("mqtt_host") or "").strip()
    if not mqtt_host:
        raise RuntimeError("mqtt_host non configurato nelle opzioni dell'add-on")
    mode = str(options.get("provisioning_mode") or "manual").strip().lower()
    if mode not in PROVISIONING_MODES:
        raise RuntimeError(f"provisioning_mode non valido: {mode!r} (ammessi: {', '.join(PROVISIONING_MODES)})")
    mqtt_password = options.get("mqtt_password") or None
    password_file = (options.get("mqtt_password_file") or "").strip() or None
    if password_file:
        if not (Path(password_file).is_absolute() or password_file.startswith("/")):
            raise RuntimeError("mqtt_password_file deve essere un percorso assoluto")
        if not mqtt_password:
            try:
                mqtt_password = Path(password_file).read_text(encoding="utf-8").strip() or None
            except OSError:
                _LOGGER.warning("File password bootstrap non leggibile: %s", password_file)
                mqtt_password = None

    bootstrap_dedicated = bool(options.get("provisioning_bootstrap_dedicated", False))
    bootstrap_host = (options.get("provisioning_bootstrap_host") or "").strip() or None
    bootstrap_username = (options.get("provisioning_bootstrap_username") or "").strip() or None
    bootstrap_password_file = (options.get("provisioning_bootstrap_password_file") or "").strip() or None
    dedicated_values = (bootstrap_host, bootstrap_username, bootstrap_password_file)
    if bootstrap_dedicated:
        if not all(dedicated_values):
            raise RuntimeError(
                "provisioning_bootstrap_dedicated richiede host, username e password_file dedicati"
            )
        if mode == "provisioned" and (mqtt_password or password_file):
            raise RuntimeError(
                "con provisioning_mode provisioned e bootstrap dedicato non configurare mqtt_password o mqtt_password_file"
            )
        if not Path(bootstrap_password_file).is_absolute():
            raise RuntimeError("provisioning_bootstrap_password_file deve essere un percorso assoluto")
        try:
            bootstrap_password = Path(bootstrap_password_file).read_text(encoding="utf-8").strip()
        except OSError as err:
            raise RuntimeError("provisioning_bootstrap_password_file non leggibile") from err
        if not bootstrap_password:
            raise RuntimeError("provisioning_bootstrap_password_file e' vuoto")
    else:
        if any(dedicated_values):
            raise RuntimeError(
                "i campi bootstrap dedicati richiedono provisioning_bootstrap_dedicated: true"
            )
        bootstrap_host = mqtt_host
        bootstrap_username = (options.get("mqtt_username") or "").strip() or None
        bootstrap_password = mqtt_password

    ca_file = (options.get("provisioning_ca_file") or "").strip() or "/ssl/provisioning-ca.crt"
    if ca_file and not Path(ca_file).is_absolute():
        raise RuntimeError("provisioning_ca_file deve essere un percorso assoluto")
    bootstrap_ca_file = (options.get("provisioning_bootstrap_ca_file") or "").strip() or "/ssl/broker-ca.crt"
    if bootstrap_ca_file and not Path(bootstrap_ca_file).is_absolute():
        raise RuntimeError("provisioning_bootstrap_ca_file deve essere un percorso assoluto")
    request_topic = (options.get("provisioning_request_topic") or "ha/provisioning/requests").strip()
    reply_prefix = (options.get("provisioning_reply_prefix") or "ha/provisioning/replies/").strip()
    if not request_topic:
        raise RuntimeError("provisioning_request_topic non puo' essere vuoto")
    if not reply_prefix.endswith("/"):
        reply_prefix += "/"
    timeout = int(options.get("provisioning_timeout", 30))
    if not 5 <= timeout <= 600:
        raise RuntimeError("provisioning_timeout deve essere tra 5 e 600 secondi")
    bootstrap_port = int(options.get("provisioning_bootstrap_port", 8883))
    if not 1 <= bootstrap_port <= 65535:
        raise RuntimeError("provisioning_bootstrap_port non valida")
    tls_port = int(options.get("mqtt_tls_port", 8884))
    if not 1 <= tls_port <= 65535:
        raise RuntimeError("mqtt_tls_port non valida")
    tls_ca_file = (options.get("mqtt_tls_ca_file") or "").strip() or "/ssl/broker-ca.crt"
    # I test girano anche su Windows: "/ssl/..." e' assoluto nel container Linux.
    if not (Path(tls_ca_file).is_absolute() or tls_ca_file.startswith("/")):
        raise RuntimeError("mqtt_tls_ca_file deve essere un percorso assoluto")

    serial = (options.get("smartgate_serial") or "").strip().lower() or host_mac()

    return Settings(
        led_status=bool(options.get("led_status", True)),
        mqtt_host=mqtt_host,
        mqtt_port=int(options.get("mqtt_port", 1883)),
        mqtt_username=(options.get("mqtt_username") or "").strip() or None,
        mqtt_password=mqtt_password,
        mqtt_tls_port=tls_port,
        mqtt_tls_ca_file=tls_ca_file,
        mqtt_password_file=password_file,
        # "ha/in": RabbitMQ converte "/" in "." -> routing key ha.in (un "ha.in" diventerebbe ha/in)
        topic=options.get("topic") or "ha/in",
        command_topic=(options.get("command_topic") or "").strip() or default_command_topic(serial),
        smartgate_serial=serial,
        heartbeat_interval=int(options.get("heartbeat_interval", 300)),
        send_device_status=bool(options.get("send_device_status", True)),
        log_level=str(options.get("log_level", "info")),
        supervisor_token=token,
        # BUILD_VERSION (= version di config.yaml) passato dal Supervisor alla build, vedi Dockerfile
        addon_version=env.get("ADDON_VERSION") or "dev",
        provisioning_mode=mode,
        provisioning_bootstrap_dedicated=bootstrap_dedicated,
        provisioning_bootstrap_host=bootstrap_host,
        provisioning_bootstrap_username=bootstrap_username,
        provisioning_bootstrap_password_file=bootstrap_password_file,
        provisioning_bootstrap_password=bootstrap_password,
        provisioning_ca_file=ca_file,
        provisioning_common_name=(options.get("provisioning_common_name") or "").strip() or None,
        provisioning_bootstrap_port=bootstrap_port,
        provisioning_bootstrap_ca_file=bootstrap_ca_file,
        provisioning_allow_legacy_ca=bool(options.get("provisioning_allow_legacy_ca", False)),
        provisioning_request_topic=request_topic,
        provisioning_reply_prefix=reply_prefix,
        provisioning_timeout=timeout,
        provisioning_reset_identity=bool(options.get("provisioning_reset_identity", False)),
    )
