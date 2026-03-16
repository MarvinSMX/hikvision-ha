"""Push-based coordinator for Hikvision Access Control.

Architecture
------------
The Hikvision device is configured once (via PUT /ISAPI/Event/notification/httpHosts)
to POST every access event to a Home Assistant webhook URL.  No polling loop is
needed — events arrive in real-time as HTTP POST requests from the device.

Each incoming POST carries a multipart/form-data body (identical in structure
to the alertStream) with one AccessControllerEvent JSON payload per part.

The coordinator:
  1. Receives the webhook POST (async_handle_webhook)
  2. Parses the multipart body → list of event dicts
  3. Updates internal state (last event, door, access status, …)
  4. Fires a hikvision_access_event on the HA event bus
  5. Notifies entity listeners so they can update their state
"""
from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import requests
from requests.auth import HTTPDigestAuth
from aiohttp.web import Request, Response

from homeassistant.core import HomeAssistant

from .const import (
    ACCESS_DENIED_CODES,
    ACCESS_GRANTED_CODES,
    ACCESS_STATUS_DENIED,
    ACCESS_STATUS_GRANTED,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOOR_CLOSE_CODES,
    DOOR_OPEN_CODES,
    EVENT_LABELS,
    EVENT_TYPE,
    HTTP_HOSTS_PATH,
    STREAM_STATUS_CONNECTED,
    STREAM_STATUS_DISCONNECTED,
)

_LOGGER = logging.getLogger(__name__)

_ISAPI_NS = "http://www.isapi.org/ver20/XMLSchema"
# Slot used when writing to httpHosts — slot 1 is the first notification host.
_HTTP_HOST_SLOT = 1


class HikvisionCoordinator:
    """Manages state and event dispatch for a single Hikvision device."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self._host: str = config[CONF_HOST]
        self._username: str = config[CONF_USERNAME]
        self._password: str = config[CONF_PASSWORD]
        self._verify_ssl: bool = config.get(CONF_VERIFY_SSL, False)
        self.name: str = config.get(CONF_NAME, self._host)

        # Public state — read by sensor / binary_sensor entities
        self.last_event: dict[str, Any] | None = None
        self.last_person_event: dict[str, Any] | None = None
        self.door_is_open: bool | None = None
        self.last_access_status: str | None = None
        self.stream_status: str = STREAM_STATUS_DISCONNECTED

        self._listeners: list[Callable] = []

    # ------------------------------------------------------------------
    # Lifecycle (trivial for push — no polling timer to manage)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Called after entities are set up; nothing to start for push."""

    async def stop(self) -> None:
        """Called on unload; nothing to tear down for push."""

    def add_listener(self, callback: Callable) -> Callable:
        """Register a state-change listener. Returns an unsubscribe callable."""
        self._listeners.append(callback)

        def _remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(callback)

        return _remove

    # ------------------------------------------------------------------
    # Webhook handler — called by HA for every incoming device POST
    # ------------------------------------------------------------------

    async def async_handle_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: Request
    ) -> Response:
        """Receive a push notification from the device."""
        try:
            body = await request.read()
            content_type = request.headers.get("Content-Type", "")
            events = self._parse_push_body(body, content_type)
            for event in events:
                self._dispatch_event(event)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Hikvision webhook handler error: %s", exc)

        return Response(status=200)

    # ------------------------------------------------------------------
    # Device configuration — called once from __init__.py on setup
    # ------------------------------------------------------------------

    def configure_device(self, ha_url: str, webhook_id: str) -> None:
        """Configure the device to push events to the HA webhook.

        Strategy: GET the current httpHosts XML → modify only the target
        fields in slot 1 → PUT the modified XML back.  This guarantees the
        structure is byte-for-byte acceptable to the device regardless of
        firmware differences in element names or ordering.

        Runs in the executor thread (blocking requests call).
        """
        import warnings  # noqa: PLC0415
        import xml.etree.ElementTree as ET  # noqa: PLC0415

        parsed = urlparse(ha_url)
        ip_or_host = parsed.hostname or self._host
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        protocol = "HTTPS" if parsed.scheme == "https" else "HTTP"
        webhook_path = f"/api/webhook/{webhook_id}"

        base_url = f"https://{self._host}{HTTP_HOSTS_PATH}"
        auth = HTTPDigestAuth(self._username, self._password)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            # ── 1. GET current config ─────────────────────────────────────
            try:
                get_resp = requests.get(
                    base_url, auth=auth, verify=self._verify_ssl, timeout=10
                )
                get_resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Hikvision [%s]: GET httpHosts failed: %s", self._host, exc
                )
                return

            # ── 2. Parse XML and update slot 1 ────────────────────────────
            try:
                raw_xml = get_resp.text
                root = ET.fromstring(raw_xml)

                # Detect namespace from root element tag and register it
                # as the default so ET serialises without namespace prefixes.
                ns = ""
                if root.tag.startswith("{"):
                    ns = root.tag.split("}")[0][1:]
                    ET.register_namespace("", ns)
                nsp = f"{{{ns}}}" if ns else ""

                def _set(parent: ET.Element, tag: str, value: str) -> None:
                    elem = parent.find(f"{nsp}{tag}")
                    if elem is not None:
                        elem.text = value

                # Detect whether ha_url contains an IP or a hostname.
                # Hikvision uses different XML fields for each case:
                #   IP       → addressingFormatType=ipaddress + <ipAddress>
                #   hostname → addressingFormatType=hostname  + <hostName>
                try:
                    ipaddress.ip_address(ip_or_host)
                    use_ip = True
                except ValueError:
                    use_ip = False

                found = False
                for host_elem in root.findall(f"{nsp}HttpHostNotification"):
                    id_elem = host_elem.find(f"{nsp}id")
                    if id_elem is not None and id_elem.text == str(_HTTP_HOST_SLOT):
                        _set(host_elem, "url", webhook_path)
                        _set(host_elem, "portNo", str(port))
                        _set(host_elem, "protocolType", protocol)

                        if use_ip:
                            _set(host_elem, "addressingFormatType", "ipaddress")
                            _set(host_elem, "ipAddress", ip_or_host)
                            # Clear hostName if it exists
                            hn = host_elem.find(f"{nsp}hostName")
                            if hn is not None:
                                hn.text = ""
                        else:
                            _set(host_elem, "addressingFormatType", "hostname")
                            # Reuse <ipAddress> field as <hostName> if device
                            # supports it; otherwise insert a <hostName> node.
                            hn = host_elem.find(f"{nsp}hostName")
                            if hn is None:
                                at_elem = host_elem.find(
                                    f"{nsp}addressingFormatType"
                                )
                                idx = (
                                    list(host_elem).index(at_elem) + 1
                                    if at_elem is not None
                                    else 0
                                )
                                hn = ET.Element(f"{nsp}hostName")
                                host_elem.insert(idx, hn)
                            hn.text = ip_or_host
                            _set(host_elem, "ipAddress", "0.0.0.0")

                        # Ensure SubscribeEvent / eventMode is present
                        sub = host_elem.find(f"{nsp}SubscribeEvent")
                        if sub is None:
                            sub = ET.SubElement(host_elem, f"{nsp}SubscribeEvent")
                        em = sub.find(f"{nsp}eventMode")
                        if em is None:
                            em = ET.SubElement(sub, f"{nsp}eventMode")
                        em.text = "all"
                        found = True
                        break

                if not found:
                    _LOGGER.warning(
                        "Hikvision [%s]: httpHosts slot %d not found in device response",
                        self._host,
                        _HTTP_HOST_SLOT,
                    )
                    return

                # Prepend the XML declaration that ET.tostring omits by default
                modified_xml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    + ET.tostring(root, encoding="unicode")
                )

            except ET.ParseError as exc:
                _LOGGER.warning(
                    "Hikvision [%s]: could not parse httpHosts XML: %s",
                    self._host,
                    exc,
                )
                return

            # ── 3. PUT modified config ────────────────────────────────────
            try:
                resp = requests.put(
                    base_url,
                    data=modified_xml.encode("utf-8"),
                    auth=auth,
                    headers={"Content-Type": "application/xml"},
                    verify=self._verify_ssl,
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    _LOGGER.info(
                        "Hikvision [%s]: push configured → %s%s",
                        self._host,
                        ha_url,
                        webhook_path,
                    )
                    self._set_status(STREAM_STATUS_CONNECTED)
                else:
                    _LOGGER.warning(
                        "Hikvision [%s]: httpHosts PUT returned HTTP %d. Body: %s",
                        self._host,
                        resp.status_code,
                        resp.text[:400],
                    )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Hikvision [%s]: httpHosts PUT request failed: %s",
                    self._host,
                    exc,
                )

    # ------------------------------------------------------------------
    # Multipart / JSON body parsing
    # ------------------------------------------------------------------

    def _parse_push_body(self, body: bytes, content_type: str) -> list[dict]:
        """Parse the raw POST body into a list of AccessControllerEvent dicts.

        Supports two formats the device may send:
        - multipart/form-data  (same structure as alertStream, parameterFormatType=XML)
        - application/json     (plain JSON body, parameterFormatType=JSON)

        The boundary name is extracted from the Content-Type header when present;
        "MIME_boundary" is the well-known Hikvision default.
        """
        text = body.decode("utf-8", errors="ignore")

        # --- Try multipart first ---
        boundary = "--MIME_boundary"
        if "boundary=" in content_type:
            boundary_name = content_type.split("boundary=")[-1].strip().strip('"')
            boundary = f"--{boundary_name}"

        # A quick check: if the boundary string appears in the body, it's multipart.
        if boundary.lstrip("-") in text:
            return self._parse_multipart(text, boundary)

        # --- Fallback: plain JSON body (parameterFormatType=JSON) ---
        try:
            payload = json.loads(text)
            if "AccessControllerEvent" in payload:
                return [payload]
            # Device might wrap in a list
            if isinstance(payload, list):
                return [p for p in payload if "AccessControllerEvent" in p]
        except (json.JSONDecodeError, ValueError):
            pass

        _LOGGER.debug("Hikvision webhook: could not parse body (len=%d)", len(body))
        return []

    @staticmethod
    def _parse_multipart(text: str, boundary: str) -> list[dict]:
        """Split a multipart body on the given boundary and extract JSON parts."""
        results: list[dict] = []
        parts = text.split(boundary)
        for part in parts:
            part = part.strip().lstrip("-").strip()
            if not part:
                continue
            separator = "\r\n\r\n" if "\r\n\r\n" in part else "\n\n"
            if separator not in part:
                continue
            _, body_part = part.split(separator, 1)
            body_part = body_part.strip()
            if not body_part.startswith("{"):
                continue
            try:
                payload = json.loads(body_part)
                if "AccessControllerEvent" in payload:
                    results.append(payload)
            except (json.JSONDecodeError, ValueError):
                continue
        return results

    # ------------------------------------------------------------------
    # Event building
    # ------------------------------------------------------------------

    def _build_event(self, payload: dict) -> dict[str, Any]:
        """Flatten an alertStream/push AccessControllerEvent payload."""
        ace = payload.get("AccessControllerEvent", {})
        major = ace.get("majorEventType", 0)
        minor = ace.get("subEventType", 0)
        event_code = f"{major}_{minor}"
        label = EVENT_LABELS.get(event_code, event_code)

        return {
            "device_name": ace.get("deviceName", self.name),
            "ip": payload.get("ipAddress", self._host),
            "timestamp": payload.get("dateTime"),
            "major": major,
            "minor": minor,
            "event_code": event_code,
            "event_label": label,
            "inductive_type": None,
            "person_name": ace.get("name") or ace.get("employeeName"),
            "card_no": ace.get("cardNo"),
            "employee_no": ace.get("employeeNoString") or ace.get("employeeNo"),
            "serial_no": ace.get("serialNo"),
            "verify_no": ace.get("verifyNo"),
        }

    # ------------------------------------------------------------------
    # State dispatch
    # ------------------------------------------------------------------

    def _dispatch_event(self, payload: dict) -> None:
        """Update state from an alertStream payload dict and notify listeners."""
        event = self._build_event(payload)
        event_code = event["event_code"]

        if event_code in ACCESS_GRANTED_CODES:
            self.last_access_status = ACCESS_STATUS_GRANTED
            if event.get("person_name"):
                self.last_person_event = event
        elif event_code in ACCESS_DENIED_CODES:
            self.last_access_status = ACCESS_STATUS_DENIED
        elif event_code in DOOR_OPEN_CODES:
            self.door_is_open = True
        elif event_code in DOOR_CLOSE_CODES:
            self.door_is_open = False

        self.last_event = event
        self.hass.bus.async_fire(EVENT_TYPE, event)
        self._set_status(STREAM_STATUS_CONNECTED)
        self._notify_listeners()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: str) -> None:
        if self.stream_status != status:
            self.stream_status = status
            self._notify_listeners()

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                pass


