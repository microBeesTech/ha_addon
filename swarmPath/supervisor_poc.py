#!/usr/bin/env python3
"""Local, allowlisted Home Assistant API adapter for the add-on PoC."""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import logging
import os
import re
import socket
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_LOGGER = logging.getLogger("supervisor_api_poc")
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_SUPERVISOR_BYTES = 8 * 1024 * 1024
_REQUEST_TIMEOUT = 10
_BIND_RETRY_TIMEOUT = 120
_BIND_RETRY_INTERVAL = 1
_IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_ENTITY_ID_PATTERN = re.compile(r"^([a-z_][a-z0-9_]*)\.([a-z0-9_]+)$")
_BLOCKED_DOMAINS = {
    "automation",
    "auth",
    "backup",
    "config",
    "hassio",
    "homeassistant",
    "logger",
    "python_script",
    "recorder",
    "rest_command",
    "script",
    "shell_command",
    "supervisor",
    "system_log",
}


class SupervisorError(Exception):
    """A safe, status-only error returned by the Supervisor API."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Supervisor API returned HTTP {status}")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


class SupervisorClient:
    """Small REST client that keeps the Supervisor token inside the add-on."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._base_url = "http://supervisor/core/api"
        self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())

    def request(self, path: str, method: str = "GET", payload: Any = None) -> tuple[int, bytes]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=_REQUEST_TIMEOUT) as response:
                data = response.read(_MAX_SUPERVISOR_BYTES + 1)
                status = response.status
        except HTTPError as err:
            return err.code, b""
        except (OSError, URLError):
            return 0, b""
        if len(data) > _MAX_SUPERVISOR_BYTES:
            return 413, b""
        return status, data

    def get_json(self, path: str) -> tuple[int, Any]:
        status, body = self.request(path)
        if status != HTTPStatus.OK:
            raise SupervisorError(status)
        try:
            return status, json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise SupervisorError(502) from err


class AddonAPI:
    """HTTP handlers exposed only to source addresses in the configured allowlist."""

    def __init__(self, supervisor: SupervisorClient, allowlist: list[ipaddress._BaseNetwork]) -> None:
        self.supervisor = supervisor
        self.allowlist = allowlist

    def is_allowed(self, address: str) -> bool:
        try:
            peer = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped is not None:
            peer = peer.ipv4_mapped
        return any(peer.version == network.version and peer in network for network in self.allowlist)

    def entities(self) -> list[dict[str, str | None]]:
        _, states = self.supervisor.get_json("/states")
        if not isinstance(states, list):
            raise SupervisorError(502)
        result: list[dict[str, str | None]] = []
        for item in states:
            if not isinstance(item, dict):
                raise SupervisorError(502)
            entity_id = item.get("entity_id")
            state = item.get("state")
            attributes = item.get("attributes")
            if not isinstance(entity_id, str) or not isinstance(state, str):
                raise SupervisorError(502)
            name = attributes.get("friendly_name") if isinstance(attributes, dict) else None
            result.append(
                {
                    "entity_id": entity_id,
                    "name": name if isinstance(name, str) else None,
                    "state": state,
                }
            )
        return result

    def send_command(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if not _IDENTIFIER_PATTERN.fullmatch(domain) or domain in _BLOCKED_DOMAINS:
            raise ValueError("Unsupported domain")
        if not _IDENTIFIER_PATTERN.fullmatch(service):
            raise ValueError("Unsupported service")
        entity_match = _ENTITY_ID_PATTERN.fullmatch(entity_id)
        if entity_match is None or entity_match.group(1) != domain:
            raise ValueError("Target entity domain must match the service domain")
        if not isinstance(data, dict) or {"entity_id", "area_id", "device_id", "target"} & data.keys():
            raise ValueError("Service data cannot override the target")

        state_path = f"/states/{quote(entity_id, safe='')}"
        try:
            _, initial = self.supervisor.get_json(state_path)
        except SupervisorError as err:
            if err.status == HTTPStatus.NOT_FOUND:
                raise LookupError("Entity not found") from err
            raise
        if not isinstance(initial, dict) or initial.get("entity_id") != entity_id:
            raise SupervisorError(502)

        service_status, _ = self.supervisor.request(
            f"/services/{domain}/{service}",
            method="POST",
            payload={"entity_id": entity_id, **data},
        )
        command_id = str(uuid.uuid4())
        if service_status != HTTPStatus.OK:
            return {
                "command_id": command_id,
                "service": {"accepted": False, "http_status": service_status},
                "observed_state": None,
            }

        try:
            observed_status, observed = self.supervisor.get_json(state_path)
        except SupervisorError as err:
            observed_status = err.status
            observed_state = None
        else:
            if not isinstance(observed, dict) or observed.get("entity_id") != entity_id:
                observed_status = HTTPStatus.BAD_GATEWAY
                observed_state = None
            else:
                state = observed.get("state")
                if isinstance(state, str):
                    observed_state = state
                else:
                    observed_status = HTTPStatus.BAD_GATEWAY
                    observed_state = None
        return {
            "command_id": command_id,
            "service": {"accepted": True, "http_status": service_status},
            "observed_state": {"http_status": observed_status, "state": observed_state},
        }

def create_handler(api: AddonAPI) -> type[BaseHTTPRequestHandler]:
    """Create a handler bound to one API instance."""

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(_REQUEST_TIMEOUT)
        server_version = "swarmPath-PoC"
        sys_version = ""

        def _send_json(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorize_peer(self) -> bool:
            if api.is_allowed(self.client_address[0]):
                return True
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "client_not_allowed"})
            return False

        def do_GET(self) -> None:
            if not self._authorize_peer():
                return
            path = urlsplit(self.path).path
            if self.path != path:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "query_not_supported"})
                return
            if path == "/health":
                self._send_json(HTTPStatus.OK, {"ok": True})
                return
            if path != "/entities":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                entities = api.entities()
            except SupervisorError as err:
                _LOGGER.warning("Supervisor entity request failed with HTTP %s", err.status)
                self._send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {"error": "supervisor_request_failed", "supervisor_http_status": err.status},
                )
                return
            self._send_json(HTTPStatus.OK, {"entities": entities})

        def do_POST(self) -> None:
            if not self._authorize_peer():
                return
            if self.path != "/commands":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if self.headers.get("Transfer-Encoding") is not None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "transfer_encoding_not_supported"})
                return
            if self.headers.get_content_type() != "application/json":
                self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "application_json_required"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_json(HTTPStatus.LENGTH_REQUIRED, {"error": "content_length_required"})
                return
            if content_length < 0 or content_length > _MAX_REQUEST_BYTES:
                self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request_too_large"})
                return
            try:
                payload = json.loads(self.rfile.read(content_length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            if not isinstance(payload, dict) or set(payload) not in ({"domain", "service", "target"}, {"domain", "service", "target", "data"}):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "domain_service_target_required"})
                return
            domain = payload["domain"]
            service = payload["service"]
            target = payload["target"]
            data = payload.get("data", {})
            if (
                not isinstance(domain, str)
                or not isinstance(service, str)
                or not isinstance(target, dict)
                or set(target) != {"entity_id"}
                or not isinstance(target["entity_id"], str)
                or not isinstance(data, dict)
            ):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_command_shape"})
                return
            try:
                result = api.send_command(domain, service, target["entity_id"], data)
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unsupported_command"})
                return
            except LookupError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "entity_not_found"})
                return
            except SupervisorError as err:
                _LOGGER.warning("Supervisor command failed with HTTP %s", err.status)
                self._send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {"error": "supervisor_request_failed", "supervisor_http_status": err.status},
                )
                return
            response_status = (
                HTTPStatus.BAD_GATEWAY
                if result["service"]["http_status"] != HTTPStatus.OK
                else HTTPStatus.OK
            )
            self._send_json(response_status, result)

        def log_message(self, format_string: str, *args: Any) -> None:
            _LOGGER.info("%s - %s", self.client_address[0], format_string % args)

    return Handler


def parse_allowlist(value: str, bind_ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> list[ipaddress._BaseNetwork]:
    try:
        raw_networks = json.loads(value)
    except json.JSONDecodeError as err:
        raise ValueError("Allowlist must be a JSON list") from err
    if not isinstance(raw_networks, list) or not raw_networks:
        raise ValueError("Allowlist must be a non-empty JSON list")
    networks: list[ipaddress._BaseNetwork] = []
    for item in raw_networks:
        if not isinstance(item, str):
            raise ValueError("Allowlist entries must be strings")
        networks.append(ipaddress.ip_network(item, strict=False))
    if not bind_ip.is_loopback and any(network.prefixlen == 0 for network in networks):
        raise ValueError("Non-loopback bind cannot use a /0 allowlist")
    return networks


def create_server(
    server_class: type[ThreadingHTTPServer],
    address: tuple[str, int],
    handler: type[BaseHTTPRequestHandler],
    *,
    retry_timeout: float = _BIND_RETRY_TIMEOUT,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ThreadingHTTPServer:
    deadline = monotonic() + retry_timeout
    warned = False
    while True:
        try:
            return server_class(address, handler)
        except OSError as err:
            if err.errno != errno.EADDRNOTAVAIL:
                raise
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise
            if not warned:
                _LOGGER.warning(
                    "API bind address %s not available yet; retrying for up to %s seconds",
                    address[0],
                    retry_timeout,
                )
                warned = True
            sleep(min(_BIND_RETRY_INTERVAL, remaining))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--allowed-clients-json", required=True)
    args = parser.parse_args()

    try:
        bind_ip = ipaddress.ip_address(args.bind)
        if not 1 <= args.port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        allowlist = parse_allowlist(args.allowed_clients_json, bind_ip)
    except ValueError as err:
        parser.error(str(err))

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        parser.error("SUPERVISOR_TOKEN is required")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api = AddonAPI(SupervisorClient(token), allowlist)
    family = socket.AF_INET6 if bind_ip.version == 6 else socket.AF_INET
    server_class = type(
        "PoCServer",
        (ThreadingHTTPServer,),
        {"address_family": family, "daemon_threads": True, "allow_reuse_address": True},
    )
    server = create_server(server_class, (str(bind_ip), args.port), create_handler(api))
    _LOGGER.info("PoC API listening on %s:%s", bind_ip, args.port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())