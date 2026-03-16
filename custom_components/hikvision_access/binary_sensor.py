"""Binary sensor entities for Hikvision Access Control."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import BINARY_SENSOR_ACTIVE_SECONDS, DOMAIN
from .coordinator import HikvisionStreamCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hikvision binary sensors from a config entry."""
    coordinator: HikvisionStreamCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HikvisionLastEventActiveSensor(coordinator, entry),
            HikvisionDoorSensor(coordinator, entry),
        ]
    )


def _device_info(coordinator: HikvisionStreamCoordinator, entry: ConfigEntry) -> dict:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": coordinator.name,
        "manufacturer": "Hikvision",
        "model": "Access Controller",
        "configuration_url": f"https://{entry.data['host']}",
    }


class HikvisionLastEventActiveSensor(BinarySensorEntity):
    """Pulses ON for a few seconds on every incoming event (any type).

    Useful as a general 'something happened at the door' trigger.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator: HikvisionStreamCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_event_active"
        self._attr_name = f"{coordinator.name} Event Active"
        self._attr_is_on = False
        self._reset_task: Any = None
        self._unsub: Any = None
        self._attr_device_info = _device_info(coordinator, entry)

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
        if self._reset_task:
            self._reset_task()

    @callback
    def _handle_update(self) -> None:
        if self._coordinator.last_event is None:
            return
        self._attr_is_on = True
        self.async_write_ha_state()
        if self._reset_task:
            self._reset_task()
        self._reset_task = async_call_later(
            self.hass,
            BINARY_SENSOR_ACTIVE_SECONDS,
            self._async_reset,
        )

    @callback
    def _async_reset(self, _now: Any = None) -> None:
        self._attr_is_on = False
        self._reset_task = None
        self.async_write_ha_state()


class HikvisionDoorSensor(BinarySensorEntity):
    """Real-time door contact state derived from the event stream.

    on  = door is open  (event 5_22)
    off = door is closed (event 5_21)
    unknown = no door event received since HA start
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, coordinator: HikvisionStreamCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_door"
        self._attr_name = f"{coordinator.name} Tür"
        self._unsub: Any = None
        self._attr_device_info = _device_info(coordinator, entry)

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    @property
    def is_on(self) -> bool | None:
        return self._coordinator.door_is_open

    @property
    def icon(self) -> str:
        if self._coordinator.door_is_open is True:
            return "mdi:door-open"
        if self._coordinator.door_is_open is False:
            return "mdi:door-closed"
        return "mdi:door"

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
