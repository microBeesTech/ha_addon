"""Client bootstrap del provisioning (M2): invia il CSR e attende la risposta del backend.

Il canale e' MQTT TLS con le credenziali bootstrap configurate dall'operatore. Il
client non usa mai le credenziali operative e non apre la connessione mTLS con il
certificato emesso: quella e' M4. Non disabilita la verifica TLS; l'eccezione
legacy per la CA del laboratorio e' esplicita e richiede un file CA.
"""

from __future__ import annotations

import json
import logging
import queue
import random
import ssl
import threading
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from .config import Settings
from .identity import GatewayIdentity, IdentityError, IdentityState, IdentityStore

_LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
REQUEST_MESSAGE_TYPE = "provisioning_request"
REPLY_MESSAGE_TYPE = "provisioning_reply"
REPLY_STATUSES = {"pending", "approved", "rejected", "conflict", "error"}


class ProvisioningError(RuntimeError):
    """Errore del canale bootstrap o risposta non valida."""


def build_request(identity: GatewayIdentity, addon_version: str | None = None) -> str:
    """Payload JSON della richiesta; contiene solo la chiave pubblica sotto forma di CSR."""

    return json.dumps(
        {
            "protocol_version": PROTOCOL_VERSION,
            "message_type": REQUEST_MESSAGE_TYPE,
            "request_id": identity.request_id,
            "smartgate_serial": identity.serial,
            "addon_version": addon_version or identity.addon_version,
            "csr_pem": identity.csr_pem,
        },
        separators=(",", ":"),
        ensure_ascii=True,
    )


def parse_reply(payload: bytes, expected_request_id: str) -> dict[str, Any]:
    """Legge e valida una risposta; solleva ProvisioningError se non e' correlabile."""

    try:
        reply = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as err:
        raise ProvisioningError("risposta non JSON") from err
    if not isinstance(reply, dict):
        raise ProvisioningError("risposta non oggetto JSON")
    if reply.get("protocol_version") != PROTOCOL_VERSION:
        raise ProvisioningError(f"protocol_version inattesa: {reply.get('protocol_version')!r}")
    if reply.get("message_type") != REPLY_MESSAGE_TYPE:
        raise ProvisioningError(f"message_type inatteso: {reply.get('message_type')!r}")
    if reply.get("request_id") != expected_request_id:
        raise ProvisioningError("request_id della risposta diverso dalla richiesta")
    status = reply.get("status")
    if status not in REPLY_STATUSES:
        raise ProvisioningError(f"stato della risposta sconosciuto: {status!r}")
    if not isinstance(reply.get("retryable"), bool):
        raise ProvisioningError("campo retryable mancante o non booleano")
    if status == "approved":
        if not isinstance(reply.get("certificate_pem"), str) or not reply["certificate_pem"].strip():
            raise ProvisioningError("risposta approved senza certificato")
        chain = reply.get("chain_pem")
        if chain is not None and not isinstance(chain, list):
            raise ProvisioningError("chain_pem non e' una lista")
    return reply


def reply_bundle(reply: dict[str, Any]) -> str:
    """Unisce foglia e catena in un unico PEM, nell'ordine atteso dalla verifica."""

    certificate = reply.get("certificate_pem")
    if not isinstance(certificate, str) or not certificate.strip():
        raise ProvisioningError("risposta senza certificato")
    parts = [certificate.strip()]
    for item in reply.get("chain_pem") or []:
        if not isinstance(item, str) or not item.strip():
            raise ProvisioningError("catena del certificato non valida")
        parts.append(item.strip())
    return "\n".join(parts) + "\n"


def create_ssl_context(ca_file: str | None, allow_legacy_ca: bool) -> ssl.SSLContext:
    """TLS del broker con verifica della catena e del nome host sempre attiva."""

    if allow_legacy_ca and not ca_file:
        raise ProvisioningError("allow_legacy_ca richiede un file CA esplicito")
    context = ssl.create_default_context(cafile=ca_file or None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    if allow_legacy_ca:
        # Solo per il laboratorio: allenta il profilo X.509, non la catena, il nome o le scadenze.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


class ProvisioningClient:
    """Una connessione bootstrap per tentativo: pubblica la richiesta e attende la reply correlata."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10)
        self._reply_topic = ""
        self._connected = threading.Event()
        self._subscribed = threading.Event()
        self._connect_error: list[str] = []
        self._client = self._build_client()

    def _build_client(self) -> mqtt.Client:
        serial = self._settings.smartgate_serial.replace(":", "")
        bootstrap_username = self._settings.provisioning_bootstrap_username
        bootstrap_password = self._settings.provisioning_bootstrap_password
        bootstrap_host = self._settings.provisioning_bootstrap_host
        if self._settings.provisioning_bootstrap_dedicated:
            if not bootstrap_host or not bootstrap_username or not bootstrap_password:
                raise ProvisioningError("configurazione bootstrap dedicata incompleta")
        else:
            bootstrap_host = bootstrap_host or self._settings.mqtt_host
            bootstrap_username = bootstrap_username or self._settings.mqtt_username
            bootstrap_password = bootstrap_password or self._settings.mqtt_password
        self._bootstrap_host = bootstrap_host
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha-mqtt-provisioning-{serial}",
        )
        if bootstrap_username:
            client.username_pw_set(bootstrap_username, bootstrap_password)
        client.tls_set_context(
            create_ssl_context(
                self._settings.provisioning_bootstrap_ca_file,
                self._settings.provisioning_allow_legacy_ca,
            )
        )
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        return client

    def request(self, identity: GatewayIdentity, timeout: float) -> dict[str, Any]:
        self._reply_topic = self._settings.provisioning_reply_prefix + identity.request_id
        self._connected.clear()
        self._subscribed.clear()
        self._connect_error = []
        try:
            self._client.connect(
                self._bootstrap_host,
                self._settings.provisioning_bootstrap_port,
                keepalive=30,
            )
            self._client.loop_start()
            if not self._connected.wait(timeout):
                raise ProvisioningError("timeout di connessione al broker bootstrap")
            if self._connect_error:
                raise ProvisioningError(f"connessione bootstrap rifiutata: {self._connect_error[0]}")
            if not self._subscribed.wait(timeout):
                raise ProvisioningError("timeout della sottoscrizione al topic di risposta")
            if self._connect_error:
                raise ProvisioningError(f"sottoscrizione bootstrap rifiutata: {self._connect_error[0]}")

            info = self._client.publish(
                self._settings.provisioning_request_topic,
                build_request(identity, self._settings.addon_version),
                qos=1,
                retain=False,
            )
            info.wait_for_publish(timeout=timeout)
            if not info.is_published():
                raise ProvisioningError("pubblicazione della richiesta non confermata")

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProvisioningError("timeout della risposta di provisioning")
                try:
                    reply = self._queue.get(timeout=remaining)
                except queue.Empty as err:
                    raise ProvisioningError("timeout della risposta di provisioning") from err
                if reply.get("request_id") == identity.request_id:
                    return parse_reply(json.dumps(reply).encode("utf-8"), identity.request_id)
        finally:
            try:
                self._client.disconnect()
            finally:
                self._client.loop_stop()

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code.is_failure:
            self._connect_error.append(str(reason_code))
            self._connected.set()
            return
        client.subscribe(self._reply_topic, qos=1)
        self._connected.set()

    def _on_subscribe(self, client: mqtt.Client, userdata: Any, mid: int, reason_codes: Any, properties: Any) -> None:
        for reason_code in reason_codes:
            if getattr(reason_code, "is_failure", False):
                self._connect_error.append(f"sottoscrizione rifiutata: {reason_code}")
                break
        self._subscribed.set()

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        if message.topic != self._reply_topic:
            return
        try:
            reply = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        try:
            self._queue.put_nowait(reply)
        except queue.Full:
            _LOGGER.warning("Risposte di provisioning in eccesso: scartata l'ultima")


def run_provisioning(settings: Settings, store: IdentityStore) -> None:
    """Ciclo di richiesta/attesa. Esce solo su stato terminale o certificato operativo."""

    if settings.provisioning_allow_legacy_ca and not settings.provisioning_bootstrap_ca_file:
        raise ProvisioningError("provisioning_allow_legacy_ca richiede provisioning_bootstrap_ca_file")
    if settings.provisioning_bootstrap_ca_file and not Path(settings.provisioning_bootstrap_ca_file).is_file():
        raise ProvisioningError(
            f"CA TLS del broker non trovata: {settings.provisioning_bootstrap_ca_file}"
        )
    if settings.provisioning_ca_file and not Path(settings.provisioning_ca_file).is_file():
        raise ProvisioningError(f"CA di provisioning non trovata: {settings.provisioning_ca_file}")
    # Fallisce subito se la CA non e' leggibile/valida, invece di ritentare all'infinito.
    create_ssl_context(
        settings.provisioning_bootstrap_ca_file,
        settings.provisioning_allow_legacy_ca,
    )

    delay = 5.0
    while True:
        identity = store.load_or_create()
        _LOGGER.info(
            "Identita' del gateway: serial %s, request_id %s, stato %s, chiave %s",
            identity.serial,
            identity.request_id,
            identity.state.value,
            identity.public_key_sha256,
        )
        if identity.last_error:
            _LOGGER.warning("Ultimo errore di provisioning: %s", identity.last_error)

        if identity.state is IdentityState.OPERATIONAL:
            _LOGGER.info("Certificato gateway operativo e verificato")
            return
        if identity.state in (IdentityState.REJECTED, IdentityState.INVALID_IDENTITY, IdentityState.EXPIRED):
            raise ProvisioningError(f"identita' non utilizzabile: stato {identity.state.value}")
        if identity.state is IdentityState.CERTIFICATE_RECEIVED and identity.certificate_pem:
            raise ProvisioningError(
                "certificato presente ma non verificabile: configurare provisioning_ca_file con la CA emittente"
            )

        try:
            reply = ProvisioningClient(settings).request(identity, float(settings.provisioning_timeout))
        except Exception as err:  # rete, TLS, broker, timeout: si ritenta con lo stesso request_id
            _LOGGER.warning("Provisioning non riuscito (%s), nuovo tentativo tra %.0fs", err, delay)
            time.sleep(delay * random.uniform(0.8, 1.2))
            delay = min(delay * 2, 300.0)
            continue

        status = reply["status"]
        if status == "approved":
            try:
                identity = store.save_certificate(reply_bundle(reply))
            except IdentityError as err:
                raise ProvisioningError(f"certificato rifiutato: {err}") from err
            _LOGGER.info("Certificato ricevuto e verificato: stato %s", identity.state.value)
            if identity.state is IdentityState.OPERATIONAL:
                return
            raise ProvisioningError(f"certificato salvato ma non operativo: stato {identity.state.value}")

        if status == "pending":
            _LOGGER.info(
                "Provisioning in attesa (%s): il gateway deve essere reclamato; nuovo tentativo tra %.0fs",
                reply.get("error_code"),
                delay,
            )
            time.sleep(delay * random.uniform(0.8, 1.2))
            delay = min(delay * 2, 300.0)
            continue

        if status == "error" and reply.get("retryable"):
            _LOGGER.warning(
                "Provisioning temporaneamente non disponibile (%s), nuovo tentativo tra %.0fs",
                reply.get("error_code"),
                delay,
            )
            time.sleep(delay * random.uniform(0.8, 1.2))
            delay = min(delay * 2, 300.0)
            continue

        if status == "error":
            reason = f"{reply.get('error_code')}: {reply.get('error_message') or 'errore terminale'}"
            try:
                store.reject(reason)
            except IdentityError:
                _LOGGER.error("Errore terminale non registrato nel record di identita'")
            raise ProvisioningError(f"provisioning non disponibile: {reason}")

        if status in ("rejected", "conflict"):
            reason = f"{reply.get('error_code')}: {reply.get('error_message') or status}"
            try:
                store.reject(reason)
            except IdentityError:
                _LOGGER.error("Rifiuto non registrato nel record di identita'")
            raise ProvisioningError(f"provisioning rifiutato: {reason}")

        raise ProvisioningError(f"risposta di provisioning non gestita: {status}")
