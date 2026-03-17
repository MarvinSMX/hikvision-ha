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
# Preferred slot for HTTP notification.  The device may reserve slot 1 for
# EHome (Hikvision's proprietary protocol), so we auto-detect the best slot.


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
        content_type = request.headers.get("Content-Type", "<none>")
        _LOGGER.info(
            "Hikvision [%s]: ▶ webhook POST from %s  Content-Type: %s",
            self._host,
            request.remote,
            content_type,
        )
        try:
            body = await request.read()
            # Log raw body so we can see exactly what the device sends.
            # Shown at WARNING so it's visible even without debug logging.
            _LOGGER.warning(
                "Hikvision [%s]: raw body (%d bytes):\n%s",
                self._host,
                len(body),
                body.decode("utf-8", errors="replace")[:1000],
            )
            events = self._parse_push_body(body, content_type)
            if not events:
                _LOGGER.warning(
                    "Hikvision [%s]: ⚠ webhook received but 0 events parsed "
                    "(unexpected body format — see raw body above)",
                    self._host,
                )
            for event in events:
                self._dispatch_event(event)
                _LOGGER.info(
                    "Hikvision [%s]: ✓ event — %s (%s) person=%s",
                    self._host,
                    event.get("event_label"),
                    event.get("event_code"),
                    event.get("person_name") or "—",
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Hikvision [%s]: webhook handler error: %s", self._host, exc
            )

        return Response(status=200)

    # ------------------------------------------------------------------
    # Device configuration — called once from __init__.py on setup
    # ------------------------------------------------------------------

    def configure_device(self, ha_url: str, webhook_id: str) -> bool:
        """Returns True if the device was successfully configured."""
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
                return False

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

                all_slots = root.findall(f"{nsp}HttpHostNotification")

                def _best_slot() -> ET.Element | None:
                    """Pick the slot to write our webhook config into.

                    Priority:
                    1. Slot that already has our webhook URL (update in-place)
                    2. First HTTP slot that isn't EHome
                    3. Any slot that isn't EHome
                    """
                    http_candidate: ET.Element | None = None
                    any_candidate: ET.Element | None = None
                    for s in all_slots:
                        proto = (s.findtext(f"{nsp}protocolType") or "").upper()
                        url_text = s.findtext(f"{nsp}url") or ""
                        if webhook_path in url_text:
                            return s  # already our slot
                        if proto in ("HTTP", "HTTPS") and http_candidate is None:
                            http_candidate = s
                        if proto != "EHOME" and any_candidate is None:
                            any_candidate = s
                    return http_candidate or any_candidate

                target = _best_slot()
                if target is None:
                    _LOGGER.warning(
                        "Hikvision [%s]: no suitable httpHosts slot found", self._host
                    )
                    return False

                slot_id = (target.findtext(f"{nsp}id") or "?")
                _LOGGER.info(
                    "Hikvision [%s]: using httpHosts slot %s for webhook",
                    self._host,
                    slot_id,
                )

                _set(target, "url", webhook_path)
                _set(target, "portNo", str(port))
                _set(target, "protocolType", protocol)

                if use_ip:
                    _set(target, "addressingFormatType", "ipaddress")
                    _set(target, "ipAddress", ip_or_host)
                    hn = target.find(f"{nsp}hostName")
                    if hn is not None:
                        hn.text = ""
                else:
                    _set(target, "addressingFormatType", "hostname")
                    hn = target.find(f"{nsp}hostName")
                    if hn is None:
                        at_elem = target.find(f"{nsp}addressingFormatType")
                        idx = (
                            list(target).index(at_elem) + 1
                            if at_elem is not None
                            else 0
                        )
                        hn = ET.Element(f"{nsp}hostName")
                        target.insert(idx, hn)
                    hn.text = ip_or_host
                    _set(target, "ipAddress", "0.0.0.0")

                # Ensure SubscribeEvent / eventMode is present
                sub = target.find(f"{nsp}SubscribeEvent")
                if sub is None:
                    sub = ET.SubElement(target, f"{nsp}SubscribeEvent")
                em = sub.find(f"{nsp}eventMode")
                if em is None:
                    em = ET.SubElement(sub, f"{nsp}eventMode")
                em.text = "all"

                # Prepend the XML declaration that ET.tostring omits by default
                modified_xml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    + ET.tostring(root, encoding="unicode")
                )
                _LOGGER.warning(
                    "Hikvision [%s]: PUT XML body:\n%s", self._host, modified_xml
                )

            except ET.ParseError as exc:
                _LOGGER.warning(
                    "Hikvision [%s]: could not parse httpHosts XML: %s",
                    self._host,
                    exc,
                )
                return False

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
                    return True  # caller sets status from event loop
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
        return False

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


