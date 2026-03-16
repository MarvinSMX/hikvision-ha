"""Stream coordinator for Hikvision Access Control."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import requests
from requests.auth import HTTPDigestAuth

from homeassistant.core import HomeAssistant

from .const import (
    ACCESS_DENIED_CODES,
    ACCESS_GRANTED_CODES,
    ACCESS_STATUS_DENIED,
    ACCESS_STATUS_GRANTED,
    ACE_MAJOR_ACCESS,
    ACE_SUB_DOOR_CLOSED,
    ACE_SUB_DOOR_OPEN,
    ACE_SUB_PERSON_VERIFIED,
    BINARY_SENSOR_ACTIVE_SECONDS,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    EVENT_LABELS,
    EVENT_TYPE,
    RECONNECT_DELAY,
    STREAM_PATH,
    STREAM_STATUS_CONNECTED,
    STREAM_STATUS_DISCONNECTED,
    STREAM_STATUS_RECONNECTING,
)

_LOGGER = logging.getLogger(__name__)


class HikvisionStreamCoordinator:
    """Manages the persistent alertStream connection and dispatches events."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self._host: str = config[CONF_HOST]
        self._username: str = config[CONF_USERNAME]
        self._password: str = config[CONF_PASSWORD]
        self._verify_ssl: bool = config.get(CONF_VERIFY_SSL, False)
        self.name: str = config.get(CONF_NAME, self._host)

        self._url = f"https://{self._host}{STREAM_PATH}"
        self._thread: threading.Thread | None = None
        self._running = False

        self.last_event: dict[str, Any] | None = None
        self.last_person_event: dict[str, Any] | None = None
        self.door_is_open: bool | None = None      # None = unknown until first door event
        self.last_access_status: str | None = None  # "granted" | "denied" | None
        self.stream_status: str = STREAM_STATUS_DISCONNECTED

        self._listeners: list[Callable] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background stream thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._stream_loop,
            name=f"hikvision_access_{self._host}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background stream thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def add_listener(self, callback: Callable) -> Callable:
        """Register a listener called whenever state changes (entities update)."""
        self._listeners.append(callback)

        def _remove() -> None:
            self._listeners.remove(callback)

        return _remove

    # ------------------------------------------------------------------
    # Internal stream loop (runs in thread)
    # ------------------------------------------------------------------

    def _stream_loop(self) -> None:
        """Outer reconnect loop – keeps running until stop() is called."""
        while self._running:
            self._set_status(STREAM_STATUS_RECONNECTING)
            try:
                self._connect_and_read()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Hikvision stream error (%s): %s", self._host, exc)

            if self._running:
                _LOGGER.info(
                    "Hikvision stream disconnected – retrying in %ds", RECONNECT_DELAY
                )
                self._set_status(STREAM_STATUS_DISCONNECTED)
                time.sleep(RECONNECT_DELAY)

    def _connect_and_read(self) -> None:
        """Open the HTTP connection and process the multipart stream."""
        auth = HTTPDigestAuth(self._username, self._password)

        with requests.get(
            self._url,
            auth=auth,
            stream=True,
            verify=self._verify_ssl,
            timeout=(10, None),  # (connect_timeout, read_timeout=infinite)
        ) as resp:
            resp.raise_for_status()

            boundary = self._extract_boundary(resp.headers.get("Content-Type", ""))
            _LOGGER.info(
                "Connected to Hikvision alertStream at %s (boundary=%r)",
                self._url,
                boundary,
            )
            self._set_status(STREAM_STATUS_CONNECTED)

            buffer = b""
            sep = f"--{boundary}".encode()

            for chunk in resp.iter_content(chunk_size=4096):
                if not self._running:
                    break
                buffer += chunk
                buffer = self._process_buffer(buffer, sep)

    # ------------------------------------------------------------------
    # Buffer / part processing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_boundary(content_type: str) -> str:
        """Extract boundary value from Content-Type header, fallback to MIME_boundary."""
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                return part[len("boundary="):].strip('"')
        return "MIME_boundary"

    def _process_buffer(self, buffer: bytes, sep: bytes) -> bytes:
        """Extract and handle complete multipart parts from the buffer."""
        while sep in buffer:
            first = buffer.find(sep)
            second = buffer.find(sep, first + len(sep))
            if second == -1:
                # Keep only from the first boundary onwards (may be incomplete)
                return buffer[first:]
            part = buffer[first + len(sep) : second]
            buffer = buffer[second:]
            self._handle_part(part)
        return buffer

    def _handle_part(self, part: bytes) -> None:
        """Parse a single multipart part and fire a HA event if it contains JSON."""
        part = part.strip()
        if not part:
            return

        # Split headers from body
        if b"\r\n\r\n" in part:
            _headers_raw, body = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            _headers_raw, body = part.split(b"\n\n", 1)
        else:
            return

        body = body.strip()
        if not body.startswith(b"{"):
            return

        try:
            payload: dict = json.loads(body)
        except json.JSONDecodeError:
            _LOGGER.debug("Failed to decode JSON in stream part")
            return

        event = self._build_event(payload)
        self.last_event = event
        self.hass.loop.call_soon_threadsafe(self._dispatch_event, event)

    def _build_event(self, payload: dict) -> dict[str, Any]:
        """Flatten the raw payload into a clean event dict."""
        ace: dict = payload.get("AccessControllerEvent", {})
        major = ace.get("majorEventType")
        sub = ace.get("subEventType")
        event_code = f"{major}_{sub}"
        return {
            "device_name": ace.get("deviceName"),
            "ip": payload.get("ipAddress"),
            "timestamp": payload.get("dateTime"),
            "event_type": payload.get("eventType"),
            "event_state": payload.get("eventState"),
            "major": major,
            "sub": sub,
            "event_code": event_code,
            "event_label": EVENT_LABELS.get(event_code, event_code),
            "verify_no": ace.get("verifyNo"),
            "serial_no": ace.get("serialNo"),
            "remote_host": ace.get("remoteHostAddr"),
            "attendance_status": ace.get("attendanceStatus"),
            "mask": ace.get("mask"),
            # Person fields (present on successful verification events)
            "person_name": ace.get("name"),
            "card_no": ace.get("cardNo"),
            "employee_no": ace.get("employeeNoString"),
            "verify_mode": ace.get("currentVerifyMode"),
            "raw": payload,
        }

    def _dispatch_event(self, event: dict) -> None:
        """Called in the HA event loop. Fires bus event and notifies listeners."""
        # Update derived state before notifying entities
        major = event.get("major")
        sub = event.get("sub")

        event_code = event.get("event_code", "")

        if major == ACE_MAJOR_ACCESS:
            if sub == ACE_SUB_PERSON_VERIFIED and event.get("person_name"):
                self.last_person_event = event
            elif sub == ACE_SUB_DOOR_OPEN:
                self.door_is_open = True
            elif sub == ACE_SUB_DOOR_CLOSED:
                self.door_is_open = False

        if event_code in ACCESS_GRANTED_CODES:
            self.last_access_status = ACCESS_STATUS_GRANTED
        elif event_code in ACCESS_DENIED_CODES:
            self.last_access_status = ACCESS_STATUS_DENIED

        self.hass.bus.async_fire(EVENT_TYPE, event)
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: str) -> None:
        self.stream_status = status
        if self.hass.is_running:
            self.hass.loop.call_soon_threadsafe(self._notify_listeners)

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                pass
