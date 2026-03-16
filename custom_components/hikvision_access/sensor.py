"""Sensor entities for Hikvision Access Control."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ACCESS_STATUS_DENIED, ACCESS_STATUS_GRANTED, DOMAIN
from .coordinator import HikvisionAcsPoller


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hikvision sensors from a config entry."""
    coordinator: HikvisionAcsPoller = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            HikvisionLastEventSensor(coordinator, entry),
            HikvisionLastEventTimeSensor(coordinator, entry),
            HikvisionLastPersonSensor(coordinator, entry),
            HikvisionAccessStatusSensor(coordinator, entry),
            HikvisionStreamStatusSensor(coordinator, entry),
        ]
    )


class _HikvisionBaseSensor(SensorEntity):
    """Base class for Hikvision sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HikvisionAcsPoller,
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
    """Sensor that shows a human-readable label of the last received event."""

    _attr_icon = "mdi:door-open"
    _attr_translation_key = "last_event"

    def __init__(self, coordinator: HikvisionAcsPoller, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_event"

    @property
    def native_value(self) -> str | None:
        if self._coordinator.last_event is None:
            return None
        return self._coordinator.last_event.get("event_label")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event = self._coordinator.last_event
        if event is None:
            return {}
        return {
            "event_code": event.get("event_code"),
            "inductive_type": event.get("inductive_type"),
            "device_name": event.get("device_name"),
            "ip": event.get("ip"),
            "timestamp": event.get("timestamp"),
            "major": event.get("major"),
            "minor": event.get("minor"),
            "person_name": event.get("person_name"),
            "serial_no": event.get("serial_no"),
        }


class HikvisionLastEventTimeSensor(_HikvisionBaseSensor):
    """Sensor that shows the timestamp of the last received event."""

    _attr_icon = "mdi:clock-outline"
    _attr_translation_key = "last_event_time"

    def __init__(self, coordinator: HikvisionAcsPoller, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_event_time"

    @property
    def native_value(self) -> str | None:
        if self._coordinator.last_event is None:
            return None
        return self._coordinator.last_event.get("timestamp")


class HikvisionLastPersonSensor(_HikvisionBaseSensor):
    """Sensor that shows the name of the last successfully verified person."""

    _attr_icon = "mdi:account-check"
    _attr_translation_key = "last_person"

    def __init__(self, coordinator: HikvisionAcsPoller, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_person"

    @property
    def native_value(self) -> str | None:
        if self._coordinator.last_person_event is None:
            return None
        return self._coordinator.last_person_event.get("person_name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event = self._coordinator.last_person_event
        if event is None:
            return {}
        return {
            "timestamp": event.get("timestamp"),
            "card_no": event.get("card_no"),
            "employee_no": event.get("employee_no"),
            "serial_no": event.get("serial_no"),
            "event_code": event.get("event_code"),
        }


class HikvisionAccessStatusSensor(_HikvisionBaseSensor):
    """Sensor showing the last access control outcome: granted or denied.

    The state persists until overwritten by the next access event.
    Use the hikvision_access_event bus event for reliable automation triggers
    on repeated identical outcomes.
    """

    _attr_translation_key = "access_status"

    def __init__(self, coordinator: HikvisionAcsPoller, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_access_status"

    @property
    def native_value(self) -> str | None:
        return self._coordinator.last_access_status

    @property
    def icon(self) -> str:
        if self._coordinator.last_access_status == ACCESS_STATUS_GRANTED:
            return "mdi:lock-open-variant"
        if self._coordinator.last_access_status == ACCESS_STATUS_DENIED:
            return "mdi:lock-alert"
        return "mdi:lock-question"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event = self._coordinator.last_person_event
        if event is None:
            return {}
        return {
            "person_name": event.get("person_name"),
            "timestamp": event.get("timestamp"),
            "employee_no": event.get("employee_no"),
            "card_no": event.get("card_no"),
        }


class HikvisionStreamStatusSensor(_HikvisionBaseSensor):
    """Sensor that shows the current poll connection status."""

    _attr_icon = "mdi:lan-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "stream_status"

    def __init__(self, coordinator: HikvisionAcsPoller, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_stream_status"

    @property
    def native_value(self) -> str:
        return self._coordinator.stream_status

    @property
    def icon(self) -> str:
        if self._coordinator.stream_status == "connected":
            return "mdi:lan-connect"
        return "mdi:lan-disconnect"
