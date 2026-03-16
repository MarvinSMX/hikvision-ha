"""Sensor entities for Hikvision Access Control."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    STREAM_STATUS_DISCONNECTED,
)
from .coordinator import HikvisionStreamCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hikvision sensors from a config entry."""
    coordinator: HikvisionStreamCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            HikvisionLastEventSensor(coordinator, entry),
            HikvisionLastEventTimeSensor(coordinator, entry),
            HikvisionStreamStatusSensor(coordinator, entry),
        ]
    )


class _HikvisionBaseSensor(SensorEntity):
    """Base class for Hikvision sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HikvisionStreamCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": coordinator.name,
            "manufacturer": "Hikvision",
            "model": "Access Controller",
            "configuration_url": f"https://{entry.data['host']}",
        }
        self._unsub: Any = None

    async def async_added_to_hass(self) -> None:
        """Register listener on coordinator."""
        self._unsub = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister listener."""
        if self._unsub:
            self._unsub()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HikvisionLastEventSensor(_HikvisionBaseSensor):
    """Sensor that shows the event code of the last received event."""

    _attr_icon = "mdi:door-open"
    _attr_translation_key = "last_event"

    def __init__(self, coordinator: HikvisionStreamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_event"
        self._attr_name = f"{coordinator.name} Last Event"

    @property
    def native_value(self) -> str | None:
        if self._coordinator.last_event is None:
            return None
        return self._coordinator.last_event.get("event_code")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event = self._coordinator.last_event
        if event is None:
            return {}
        return {
            "device_name": event.get("device_name"),
            "ip": event.get("ip"),
            "timestamp": event.get("timestamp"),
            "major": event.get("major"),
            "sub": event.get("sub"),
            "verify_no": event.get("verify_no"),
            "serial_no": event.get("serial_no"),
            "remote_host": event.get("remote_host"),
            "attendance_status": event.get("attendance_status"),
            "mask": event.get("mask"),
            "event_state": event.get("event_state"),
        }


class HikvisionLastEventTimeSensor(_HikvisionBaseSensor):
    """Sensor that shows the timestamp of the last received event."""

    _attr_icon = "mdi:clock-outline"
    _attr_translation_key = "last_event_time"

    def __init__(self, coordinator: HikvisionStreamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_event_time"
        self._attr_name = f"{coordinator.name} Last Event Time"

    @property
    def native_value(self) -> str | None:
        if self._coordinator.last_event is None:
            return None
        return self._coordinator.last_event.get("timestamp")


class HikvisionStreamStatusSensor(_HikvisionBaseSensor):
    """Sensor that shows the current stream connection status."""

    _attr_icon = "mdi:lan-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "stream_status"

    def __init__(self, coordinator: HikvisionStreamCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_stream_status"
        self._attr_name = f"{coordinator.name} Stream Status"

    @property
    def native_value(self) -> str:
        return self._coordinator.stream_status

    @property
    def icon(self) -> str:
        if self._coordinator.stream_status == "connected":
            return "mdi:lan-connect"
        if self._coordinator.stream_status == "reconnecting":
            return "mdi:lan-pending"
        return "mdi:lan-disconnect"
