"""Identita' persistente del gateway: chiave P-256, CSR, stato e certificato.

Il modulo non parla con la rete e non conosce il broker: prepara e conserva i
materiali che le milestone successive useranno per il provisioning e per la
connessione mTLS. La chiave privata non viene mai serializzata nei log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
KEY_FILE = "gateway-key.pem"
CSR_FILE = "gateway.csr"
CERTIFICATE_FILE = "gateway-cert.pem"
RECORD_FILE = "identity.json"


def reset_identity_files(state_dir: Path) -> bool:
    """Rimuove solo i file dell'identita', non l'intera directory ne' options.json."""

    removed = False
    for name in (KEY_FILE, CSR_FILE, CERTIFICATE_FILE, RECORD_FILE):
        try:
            (Path(state_dir) / name).unlink()
            removed = True
        except FileNotFoundError:
            continue
    return removed
SERIAL_PATTERN = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class IdentityState(StrEnum):
    """Stato persistito dell'identita', distinto dalla connessione al broker."""

    UNINITIALIZED = "uninitialized"
    PENDING = "pending"
    CERTIFICATE_RECEIVED = "certificate_received"
    OPERATIONAL = "operational"
    REJECTED = "rejected"
    INVALID_IDENTITY = "invalid_identity"
    EXPIRED = "expired"


class IdentityError(RuntimeError):
    """Identita' assente o incoerente: non si rigenera nulla in silenzio."""


class MissingTrustAnchor(IdentityError):
    """Manca la CA pubblica con cui verificare il certificato ricevuto."""


class CertificateVerificationError(IdentityError):
    """Il certificato non supera i controlli richiesti."""


class CertificateExpired(CertificateVerificationError):
    """Il certificato (o la sua CA) non e' piu' valido."""


@dataclass(frozen=True)
class GatewayIdentity:
    """Vista in sola lettura dei materiali persistenti dell'identita'."""

    serial: str
    request_id: str
    state: IdentityState
    csr_pem: str
    public_key_sha256: str
    addon_version: str = "dev"
    certificate_pem: str | None = None
    certificate_sha256: str | None = None
    certificate_not_before: datetime | None = None
    certificate_not_after: datetime | None = None
    last_error: str | None = None

    def __repr__(self) -> str:  # la chiave privata non e' un campo di questa vista
        return (
            f"GatewayIdentity(serial={self.serial}, request_id={self.request_id}, state={self.state.value}, "
            f"public_key_sha256={self.public_key_sha256}, last_error={self.last_error!r})"
        )


def public_key_der(key: Any) -> bytes:
    """DER SubjectPublicKeyInfo: stessa forma usata nel PoC per il confronto."""

    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def public_key_fingerprint(key: Any) -> str:
    return hashlib.sha256(public_key_der(key)).hexdigest()


def _certificate_fingerprint(certificate: x509.Certificate) -> str:
    return hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise IdentityError("data non valida nel record di identita'")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise IdentityError("data non valida nel record di identita'") from err
    if parsed.tzinfo is None:
        raise IdentityError("data senza fuso orario nel record di identita'")
    return parsed.astimezone(UTC)


def _same_certificate(first: x509.Certificate, second: x509.Certificate) -> bool:
    return first.public_bytes(serialization.Encoding.DER) == second.public_bytes(serialization.Encoding.DER)


def _check_validity(certificate: x509.Certificate, now: datetime, label: str) -> None:
    if now >= certificate.not_valid_after_utc:
        raise CertificateExpired(f"{label} scaduto il {_iso(certificate.not_valid_after_utc)}")
    if now < certificate.not_valid_before_utc:
        raise CertificateVerificationError(f"{label} non ancora valido dal {_iso(certificate.not_valid_before_utc)}")


def _check_ca_certificate(certificate: x509.Certificate, now: datetime, label: str) -> None:
    try:
        constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
    except x509.ExtensionNotFound as err:
        raise CertificateVerificationError(f"{label} senza Basic Constraints") from err
    if not constraints.ca:
        raise CertificateVerificationError(f"{label} non e' una CA")
    _check_validity(certificate, now, label)
    try:
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        return
    if not usage.key_cert_sign:
        raise CertificateVerificationError(f"{label} non puo' firmare certificati (keyCertSign assente)")


def _verify_issuer_chain(
    leaf: x509.Certificate,
    intermediates: list[x509.Certificate],
    trusted_ca: x509.Certificate,
    now: datetime,
) -> None:
    current = leaf
    for issuer in intermediates:
        if _same_certificate(issuer, trusted_ca):
            continue
        if _same_certificate(issuer, current):
            raise CertificateVerificationError("catena con certificato ripetuto")
        try:
            current.verify_directly_issued_by(issuer)
        except (ValueError, TypeError, InvalidSignature) as err:
            raise CertificateVerificationError("catena non valida: firma o issuer non corrispondente") from err
        _check_ca_certificate(issuer, now, "CA intermedia")
        current = issuer
    try:
        current.verify_directly_issued_by(trusted_ca)
    except (ValueError, TypeError, InvalidSignature) as err:
        raise CertificateVerificationError("certificato non firmato dalla CA attesa") from err
    _check_ca_certificate(trusted_ca, now, "CA attesa")


def verify_certificate_bundle(
    certificate_pem: str,
    private_key: ec.EllipticCurvePrivateKey,
    expected_common_name: str,
    trusted_ca_pem: bytes | str | None,
    now: datetime | None = None,
) -> x509.Certificate:
    """Verifica il certificato gateway e la catena; restituisce la foglia.

    Controlli: firma della catena verso la CA attesa, validita', CN, chiave
    pubblica corrispondente alla privata, `clientAuth`, non-CA. Non accetta
    l'assenza della CA: senza trust anchor il certificato non e' operativo.
    """

    if not trusted_ca_pem:
        raise MissingTrustAnchor("CA pubblica non configurata: impossibile verificare il certificato")
    if not expected_common_name:
        raise CertificateVerificationError("CN atteso non configurato")
    moment = now or _utc_now()
    try:
        certificates = x509.load_pem_x509_certificates(
            certificate_pem.encode() if isinstance(certificate_pem, str) else certificate_pem
        )
    except ValueError as err:
        raise CertificateVerificationError("certificato PEM non valido") from err
    if not certificates:
        raise CertificateVerificationError("certificato PEM vuoto")
    leaf = certificates[0]

    _check_validity(leaf, moment, "certificato gateway")
    if public_key_der(leaf.public_key()) != public_key_der(private_key.public_key()):
        raise CertificateVerificationError("il certificato non corrisponde alla chiave privata")
    common_names = leaf.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(common_names) != 1 or common_names[0].value != expected_common_name:
        found = common_names[0].value if common_names else "(assente)"
        raise CertificateVerificationError(
            f"CN del certificato '{found}' diverso da quello atteso '{expected_common_name}'"
        )
    try:
        constraints = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value
    except x509.ExtensionNotFound as err:
        raise CertificateVerificationError("certificato gateway senza Basic Constraints") from err
    if constraints.ca:
        raise CertificateVerificationError("il certificato gateway e' una CA")
    try:
        usage = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound as err:
        raise CertificateVerificationError("certificato gateway senza Extended Key Usage") from err
    if ExtendedKeyUsageOID.CLIENT_AUTH not in usage:
        raise CertificateVerificationError("certificato gateway non abilitato a clientAuth")

    try:
        ca_certificates = x509.load_pem_x509_certificates(
            trusted_ca_pem.encode() if isinstance(trusted_ca_pem, str) else trusted_ca_pem
        )
    except ValueError as err:
        raise CertificateVerificationError("file della CA attesa non valido") from err
    if not ca_certificates:
        raise MissingTrustAnchor("file della CA attesa vuoto")

    errors: list[CertificateVerificationError] = []
    for trusted_ca in ca_certificates:
        try:
            _verify_issuer_chain(leaf, certificates[1:], trusted_ca, moment)
            return leaf
        except CertificateVerificationError as err:
            errors.append(err)
    if errors and all(isinstance(err, CertificateExpired) for err in errors):
        raise errors[0]
    raise errors[-1]


class IdentityStore:
    """Archivio su disco dell'identita' del gateway, con scritture atomiche."""

    def __init__(
        self,
        state_dir: Path,
        serial: str,
        addon_version: str,
        *,
        common_name: str | None = None,
        trusted_ca_file: Path | None = None,
    ) -> None:
        normalized = serial.strip().lower()
        if not SERIAL_PATTERN.fullmatch(normalized):
            raise IdentityError(f"serial non valido per l'identita': {serial!r}")
        self._state_dir = Path(state_dir)
        self._serial = normalized
        self._addon_version = addon_version
        # RabbitMQ MQTT non ammette ':' nei nomi utente: CN e utente usano il
        # serial compatto, mentre il serial wire resta con i due punti.
        self._common_name = common_name or f"gateBee_{normalized.replace(':', '')}"
        self._trusted_ca_file = Path(trusted_ca_file) if trusted_ca_file else None

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    @property
    def key_path(self) -> Path:
        return self._state_dir / KEY_FILE

    @property
    def csr_path(self) -> Path:
        return self._state_dir / CSR_FILE

    @property
    def certificate_path(self) -> Path:
        return self._state_dir / CERTIFICATE_FILE

    @property
    def record_path(self) -> Path:
        return self._state_dir / RECORD_FILE

    # ------------------------------------------------------------------ API ---

    def load_or_create(self) -> GatewayIdentity:
        """Carica l'identita' o la crea al primo avvio; non rigenera mai la privata."""

        self._ensure_private_dir()
        record = self._read_record()

        key_exists = self.key_path.is_file()
        csr_exists = self.csr_path.is_file()
        certificate_exists = self.certificate_path.is_file()
        if not (key_exists or csr_exists or certificate_exists or record is not None):
            return self._bootstrap()

        if not key_exists:
            self._set_state(
                record,
                IdentityState.INVALID_IDENTITY,
                "chiave privata mancante: l'identita' non viene rigenerata automaticamente",
            )
            raise IdentityError(
                "chiave privata dell'identita' mancante: non viene rigenerata automaticamente. "
                "Ripristinare il file o autorizzare esplicitamente una nuova identita'."
            )

        private_key = self._load_private_key()
        _enforce_private_mode(self.key_path)
        _enforce_private_mode(self.record_path)
        _enforce_private_mode(self.csr_path)
        _enforce_private_mode(self.certificate_path)
        fingerprint = public_key_fingerprint(private_key.public_key())

        if record is None:
            # Crash fra la scrittura dei materiali e quella del record: la chiave
            # esistente si riusa, non si crea una seconda identita'.
            record = self._new_record(secrets.token_hex(32), IdentityState.PENDING, fingerprint)
            self._write_record(record)
            _LOGGER.warning("Record di identita' mancante: ricreato riusando la chiave esistente")

        if record.get("serial") != self._serial:
            raise IdentityError(
                f"serial configurato {self._serial} diverso da quello dell'identita' persistente "
                f"{record.get('serial')}: nessuna nuova registrazione automatica"
            )
        if record.get("public_key_sha256") != fingerprint:
            self._set_state(
                record,
                IdentityState.INVALID_IDENTITY,
                "la chiave privata non corrisponde all'impronta salvata",
            )
            raise IdentityError("la chiave privata non corrisponde all'impronta salvata nel record")

        csr_pem = self._read_text(self.csr_path) if csr_exists else None
        if csr_pem is None:
            csr_pem = self._build_csr(private_key)
            _atomic_write(self.csr_path, csr_pem.encode("ascii"), 0o600)
            _LOGGER.warning("CSR mancante: rigenerato dalla stessa chiave, stesso request_id")
        self._validate_csr(csr_pem, private_key)

        if not certificate_exists:
            if record.get("state") == IdentityState.OPERATIONAL.value:
                self._set_state(
                    record,
                    IdentityState.INVALID_IDENTITY,
                    "stato operativo senza certificato: nessuna nuova richiesta automatica",
                )
                raise IdentityError("identita' operativa ma certificato mancante: nessun reinvio automatico")
            if record.get("state") != IdentityState.REJECTED.value:
                if record.get("state") != IdentityState.PENDING.value or record.get("last_error"):
                    self._set_state(record, IdentityState.PENDING, None)
            return self._view(record, csr_pem, None)

        certificate_pem = self._read_text(self.certificate_path)
        try:
            leaf = self._verify(certificate_pem, private_key)
        except CertificateExpired as err:
            self._set_state(record, IdentityState.EXPIRED, str(err))
            return self._view(record, csr_pem, certificate_pem)
        except MissingTrustAnchor as err:
            self._set_state(record, IdentityState.CERTIFICATE_RECEIVED, str(err))
            return self._view(record, csr_pem, certificate_pem)
        except CertificateVerificationError as err:
            self._set_state(record, IdentityState.INVALID_IDENTITY, str(err))
            raise

        self._record_operational(record, leaf)
        return self._view(record, csr_pem, certificate_pem)

    def save_certificate(self, certificate_pem: str) -> GatewayIdentity:
        """Verifica e salva certificato/chain; promuove a operativo solo se valido."""

        current = self.load_or_create()
        private_key = self._load_private_key()
        record = self._read_record()
        if record is None:
            raise IdentityError("record di identita' mancante")
        try:
            leaf = self._verify(certificate_pem, private_key)
        except MissingTrustAnchor as err:
            self._set_state(record, IdentityState.CERTIFICATE_RECEIVED, str(err))
            raise
        except CertificateExpired as err:
            self._set_state(record, IdentityState.EXPIRED, str(err))
            raise
        except CertificateVerificationError as err:
            self._set_state(record, IdentityState.INVALID_IDENTITY, str(err))
            raise
        _atomic_write(self.certificate_path, certificate_pem.encode("ascii"), 0o600)
        self._record_operational(record, leaf)
        _LOGGER.info(
            "Certificato gateway verificato e salvato: CN %s, scadenza %s",
            self._common_name,
            _iso(leaf.not_valid_after_utc),
        )
        return self._view(record, current.csr_pem, certificate_pem)

    def reject(self, reason: str) -> GatewayIdentity:
        """Registra un rifiuto esplicito: non si ripete la richiesta da soli."""

        record = self._read_record()
        if record is None:
            raise IdentityError("record di identita' mancante")
        self._set_state(record, IdentityState.REJECTED, reason)
        csr_pem = self._read_text(self.csr_path)
        certificate_pem = self._read_text(self.certificate_path) if self.certificate_path.is_file() else None
        return self._view(record, csr_pem, certificate_pem)

    # ------------------------------------------------------------- bootstrap ---

    def _bootstrap(self) -> GatewayIdentity:
        private_key = ec.generate_private_key(ec.SECP256R1())
        key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        csr_pem = self._build_csr(private_key)
        request_id = secrets.token_hex(32)
        fingerprint = public_key_fingerprint(private_key.public_key())

        _atomic_write(self.key_path, key_pem, 0o600)
        _atomic_write(self.csr_path, csr_pem.encode("ascii"), 0o600)
        record = self._new_record(request_id, IdentityState.PENDING, fingerprint)
        self._write_record(record)
        _LOGGER.info(
            "Prima identita' del gateway creata: serial %s, request_id %s, chiave %s",
            self._serial,
            request_id,
            fingerprint,
        )
        return self._view(record, csr_pem, None)

    def _new_record(self, request_id: str, state: IdentityState, fingerprint: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "serial": self._serial,
            "addon_version": self._addon_version,
            "created_at": _iso(_utc_now()),
            "updated_at": _iso(_utc_now()),
            "state": state.value,
            "public_key_sha256": fingerprint,
            "certificate_sha256": None,
            "certificate_not_before": None,
            "certificate_not_after": None,
            "last_error": None,
        }

    # ------------------------------------------------------------ materiali ---

    def _build_csr(self, private_key: ec.EllipticCurvePrivateKey) -> str:
        # Il CN del CSR riporta il serial dichiarato, come nel PoC. Il CN
        # operativo (Q5) lo fissa il backend e viene verificato separatamente
        # con _common_name: il richiedente non puo' imporre l'identita' Rabbit.
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self._serial)]))
            .sign(private_key, hashes.SHA256())
        )
        return csr.public_bytes(serialization.Encoding.PEM).decode("ascii")

    def _validate_csr(self, csr_pem: str, private_key: ec.EllipticCurvePrivateKey) -> None:
        try:
            csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        except ValueError as err:
            raise IdentityError("CSR persistente non valido: nessuna rigenerazione automatica") from err
        if not csr.is_signature_valid:
            raise IdentityError("firma del CSR persistente non valida")
        if public_key_der(csr.public_key()) != public_key_der(private_key.public_key()):
            raise IdentityError("il CSR persistente non corrisponde alla chiave privata")
        common_names = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if len(common_names) != 1 or common_names[0].value != self._serial:
            raise IdentityError("il CSR persistente non riporta il serial atteso")

    def _load_private_key(self) -> ec.EllipticCurvePrivateKey:
        try:
            data = self.key_path.read_bytes()
        except OSError as err:
            raise IdentityError(f"impossibile leggere la chiave privata: {err}") from err
        try:
            key = serialization.load_pem_private_key(data, password=None)
        except (TypeError, ValueError) as err:
            raise IdentityError("chiave privata non leggibile o protetta da password") from err
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise IdentityError("la chiave privata non e' EC P-256")
        return key

    def _verify(self, certificate_pem: str, private_key: ec.EllipticCurvePrivateKey) -> x509.Certificate:
        if self._trusted_ca_file is None:
            raise MissingTrustAnchor("CA pubblica non configurata: il certificato non puo' essere verificato")
        try:
            ca_pem = self._trusted_ca_file.read_bytes()
        except OSError as err:
            raise MissingTrustAnchor(f"CA pubblica non leggibile: {err}") from err
        return verify_certificate_bundle(
            certificate_pem,
            private_key,
            self._common_name,
            ca_pem,
        )

    def _record_operational(self, record: dict[str, Any], leaf: x509.Certificate) -> None:
        record.update(
            state=IdentityState.OPERATIONAL.value,
            certificate_sha256=_certificate_fingerprint(leaf),
            certificate_not_before=_iso(leaf.not_valid_before_utc),
            certificate_not_after=_iso(leaf.not_valid_after_utc),
            last_error=None,
        )
        self._write_record(record)

    def _view(self, record: dict[str, Any], csr_pem: str, certificate_pem: str | None) -> GatewayIdentity:
        try:
            state = IdentityState(record.get("state"))
        except ValueError as err:
            raise IdentityError(f"stato di identita' sconosciuto: {record.get('state')!r}") from err
        return GatewayIdentity(
            serial=self._serial,
            request_id=str(record.get("request_id")),
            state=state,
            csr_pem=csr_pem,
            public_key_sha256=str(record.get("public_key_sha256")),
            addon_version=str(record.get("addon_version") or "dev"),
            certificate_pem=certificate_pem,
            certificate_sha256=record.get("certificate_sha256"),
            certificate_not_before=_parse_iso(record.get("certificate_not_before")),
            certificate_not_after=_parse_iso(record.get("certificate_not_after")),
            last_error=record.get("last_error"),
        )

    # --------------------------------------------------------------- disco ---

    def _ensure_private_dir(self) -> None:
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as err:
            raise IdentityError(f"impossibile creare la directory dell'identita': {err}") from err
        if os.name != "nt":
            try:
                os.chmod(self._state_dir, 0o700)
            except OSError as err:
                _LOGGER.warning("Permessi della directory dell'identita' non impostati: %s", err)

    def _read_record(self) -> dict[str, Any] | None:
        try:
            raw = self.record_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as err:
            raise IdentityError(f"impossibile leggere il record di identita': {err}") from err
        try:
            record = json.loads(raw)
        except ValueError as err:
            raise IdentityError("record di identita' non valido (JSON)") from err
        if not isinstance(record, dict):
            raise IdentityError("record di identita' non valido (non oggetto)")
        if record.get("schema_version") != SCHEMA_VERSION:
            raise IdentityError(f"versione del record di identita' non supportata: {record.get('schema_version')!r}")
        request_id = record.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
            raise IdentityError("request_id non valido nel record di identita'")
        fingerprint = record.get("public_key_sha256")
        if not isinstance(fingerprint, str) or not FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise IdentityError("impronta della chiave non valida nel record di identita'")
        return record

    def _write_record(self, record: dict[str, Any]) -> None:
        record["updated_at"] = _iso(_utc_now())
        payload = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
        _atomic_write(self.record_path, payload, 0o600)

    def _set_state(self, record: dict[str, Any] | None, state: IdentityState, error: str | None) -> None:
        if record is None:
            return
        if record.get("state") == state.value and record.get("last_error") == error:
            return
        record["state"] = state.value
        record["last_error"] = error
        self._write_record(record)

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="ascii")
        except OSError as err:
            raise IdentityError(f"impossibile leggere {path.name}: {err}") from err


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Scrittura atomica nello stesso filesystem, con permessi minimi."""

    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(directory))
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                os.chmod(temporary_path, mode)
            os.replace(temporary_path, path)
            _fsync_directory(directory)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
    except OSError as err:
        raise IdentityError(f"impossibile scrivere {path.name}: {err}") from err


def _enforce_private_mode(path: Path, mode: int = 0o600) -> None:
    if os.name == "nt" or not path.is_file():
        return
    try:
        os.chmod(path, mode)
    except OSError as err:
        _LOGGER.warning("Permessi di %s non impostati: %s", path.name, err)


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
