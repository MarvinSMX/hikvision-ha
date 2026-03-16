"""AcsEvent polling coordinator for Hikvision Access Control.

Replaces the old alertStream approach with a clean, serial-ordered poll of
/ISAPI/AccessControl/AcsEvent.  Benefits over alertStream:
- Only major=5 access events (no system noise)
- Events arrive in serial order → no dedup / debounce needed
- beginSerialNo parameter → only new events since last poll
- inductiveEventType field → semantic labels without reverse-engineering minor codes
- last_serial persisted in HA storage → survives restarts
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from collections.abc import Callable
from typing import Any

import requests
from requests.auth import HTTPDigestAuth

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    ACS_EVENT_PATH,
    ACCESS_DENIED_CODES,
    ACCESS_GRANTED_CODES,
    ACCESS_STATUS_DENIED,
    ACCESS_STATUS_GRANTED,
    BINARY_SENSOR_ACTIVE_SECONDS,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    EVENT_LABELS,
    EVENT_TYPE,
    INDUCTIVE_DENIED,
    INDUCTIVE_DOOR_CLOSE,
    INDUCTIVE_DOOR_OPEN,
    INDUCTIVE_EVENT_LABELS,
    INDUCTIVE_GRANTED,
    POLL_INTERVAL,
    STORAGE_VERSION,
    STREAM_STATUS_CONNECTED,
    STREAM_STATUS_DISCONNECTED,
)

_LOGGER = logging.getLogger(__name__)

# On first startup (no saved serial), skip events older than this threshold
# to avoid replaying the device's entire historical log.
_FIRST_STARTUP_LOOKBACK_SECONDS = 60


class HikvisionAcsPoller:
    """Polls /ISAPI/AccessControl/AcsEvent and dispatches events to HA."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self._host: str = config[CONF_HOST]
        self._username: str = config[CONF_USERNAME]
        self._password: str = config[CONF_PASSWORD]
        self._verify_ssl: bool = config.get(CONF_VERIFY_SSL, False)
        self.name: str = config.get(CONF_NAME, self._host)

        self._url = f"https://{self._host}{ACS_EVENT_PATH}?format=json"
        self._store = Store(hass, STORAGE_VERSION, f"hikvision_access.{self._host}")
        self._last_serial: int = 0
        self._cutoff: datetime | None = None  # freshness gate for first startup
        self._unsub_poll: Any = None

        # Public state — read by entities
        self.last_event: dict[str, Any] | None = None
        self.last_person_event: dict[str, Any] | None = None
        self.door_is_open: bool | None = None
        self.last_access_status: str | None = None
        self.stream_status: str = STREAM_STATUS_DISCONNECTED

        self._listeners: list[Callable] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load persisted serial, set freshness gate, start periodic poll."""
        saved = await self._store.async_load()
        self._last_serial = (saved or {}).get("last_serial", 0)

        if self._last_serial == 0:
            # No saved position → first startup.
            # Apply freshness filter so the device's historical log is not
            # replayed into HA sensors and automations.
            self._cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=_FIRST_STARTUP_LOOKBACK_SECONDS
            )
            _LOGGER.info(
                "Hikvision [%s]: first startup, events older than %s will be skipped",
                self._host,
                self._cutoff.isoformat(),
            )
        else:
            _LOGGER.info(
                "Hikvision [%s]: resuming from serial %d",
                self._host,
                self._last_serial,
            )

        # Immediate first poll (don't wait for the first interval tick)
        self.hass.async_create_task(self._async_poll())

        # Periodic poll
        self._unsub_poll = async_track_time_interval(
            self.hass,
            self._async_poll,
            timedelta(seconds=POLL_INTERVAL),
        )

    async def stop(self) -> None:
        """Cancel poll timer and persist last serial."""
        if self._unsub_poll:
            self._unsub_poll()
            self._unsub_poll = None
        await self._store.async_save({"last_serial": self._last_serial})
        _LOGGER.debug("Hikvision [%s]: saved last_serial=%d", self._host, self._last_serial)

    def add_listener(self, callback: Callable) -> Callable:
        """Register a state-change listener. Returns an unsubscribe callable."""
        self._listeners.append(callback)

        def _remove() -> None:
            self._listeners.remove(callback)

        return _remove

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _async_poll(self, _now: Any = None) -> None:
        """Fetch new events from the device (runs in HA event loop)."""
        try:
            events: list[dict] = await self.hass.async_add_executor_job(
                self._fetch_events, self._last_serial + 1
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Hikvision [%s]: poll failed: %s", self._host, exc)
            self._set_status(STREAM_STATUS_DISCONNECTED)
            return

        self._set_status(STREAM_STATUS_CONNECTED)

        for event in events:
            self._dispatch_event(event)

        # After first successful poll, lift the freshness gate so that
        # events from the last minute of offline time are processed normally.
        if self._cutoff is not None:
            self._cutoff = None

    def _fetch_events(self, begin_serial: int) -> list[dict]:
        """Runs in executor thread. Returns parsed event list."""
        xml_body = self._build_query(begin_serial)
        resp = requests.post(
            self._url,
            data=xml_body.encode("utf-8"),
            auth=HTTPDigestAuth(self._username, self._password),
            headers={"Content-Type": "application/xml"},
            verify=self._verify_ssl,
            timeout=10,
        )
        resp.raise_for_status()
        return self._parse_response(resp.json())

    # ------------------------------------------------------------------
    # Query builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_query(begin_serial: int) -> str:
        """Build the AcsEventCond XML body."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<AcsEventCond version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
            "<searchID>1</searchID>"
            "<major>5</major>"
            f"<beginSerialNo>{begin_serial}</beginSerialNo>"
            "<endSerialNo>3000000000</endSerialNo>"
            "</AcsEventCond>"
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, data: dict) -> list[dict]:
        """Extract events from the AcsEvent JSON response.

        Always advances self._last_serial, but only returns events that
        pass the freshness gate (relevant on first startup only).
        """
        acs = data.get("AcsEvent", {})

        if acs.get("responseStatusStrg") == "NO MATCH":
            return []

        items: list[dict] = acs.get("InfoList") or []
        result: list[dict] = []

        for item in items:
            serial = item.get("serialNo", 0)
            if serial > self._last_serial:
                self._last_serial = serial

            if not self._is_fresh(item):
                _LOGGER.debug(
                    "Skipping historical event serial=%d ts=%s",
                    serial,
                    item.get("time"),
                )
                continue

            result.append(self._build_event(item))

        return result

    def _is_fresh(self, item: dict) -> bool:
        """Return False for events older than the first-startup cutoff."""
        if self._cutoff is None:
            return True
        timestamp_str = item.get("time", "")
        try:
            event_time = datetime.fromisoformat(timestamp_str)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            return event_time >= self._cutoff
        except (ValueError, TypeError):
            return True  # can't parse → let through

    def _build_event(self, item: dict) -> dict[str, Any]:
        """Flatten an AcsEvent InfoList item into a clean event dict."""
        major = item.get("major", 0)
        minor = item.get("minor", 0)
        event_code = f"{major}_{minor}"
        inductive = item.get("inductiveEventType")

        # inductiveEventType gives semantic meaning directly; fall back to
        # the minor-code map for devices that don't send it.
        if inductive:
            label = INDUCTIVE_EVENT_LABELS.get(inductive, f"Typ {inductive}")
        else:
            label = EVENT_LABELS.get(event_code, event_code)

        return {
            "device_name": self.name,
            "ip": self._host,
            "timestamp": item.get("time"),
            "major": major,
            "minor": minor,
            "event_code": event_code,
            "event_label": label,
            "inductive_type": inductive,
            "person_name": item.get("name"),
            "card_no": item.get("cardNo"),
            "employee_no": item.get("employeeNoString"),
            "serial_no": item.get("serialNo"),
            # Alias kept for backward compatibility with existing automations
            "verify_no": item.get("serialNo"),
        }

    # ------------------------------------------------------------------
    # Dispatching
    # ------------------------------------------------------------------

    def _dispatch_event(self, event: dict) -> None:
        """Update coordinator state and notify entities + event bus."""
        inductive = event.get("inductive_type")
        event_code = event.get("event_code", "")

        # Semantic classification via inductiveEventType (preferred)
        if inductive in INDUCTIVE_GRANTED:
            self.last_access_status = ACCESS_STATUS_GRANTED
            if event.get("person_name"):
                self.last_person_event = event
        elif inductive in INDUCTIVE_DENIED:
            self.last_access_status = ACCESS_STATUS_DENIED
        elif inductive in INDUCTIVE_DOOR_OPEN:
            self.door_is_open = True
        elif inductive in INDUCTIVE_DOOR_CLOSE:
            self.door_is_open = False
        # Fallback: minor-code classification
        elif event_code in ACCESS_GRANTED_CODES:
            self.last_access_status = ACCESS_STATUS_GRANTED
            if event.get("person_name"):
                self.last_person_event = event
        elif event_code in ACCESS_DENIED_CODES:
            self.last_access_status = ACCESS_STATUS_DENIED

        self.last_event = event
        self.hass.bus.async_fire(EVENT_TYPE, event)
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
