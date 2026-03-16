"""Binary sensor entities for Hikvision Access Control."""
from __future__ import annotations

import asyncio
from typing import Any

from debouncer import DebounceOptions, debounce

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BINARY_SENSOR_ACTIVE_SECONDS, DOMAIN
from .coordinator import HikvisionCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hikvision binary sensors from a config entry."""
    coordinator: HikvisionCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HikvisionLastEventActiveSensor(coordinator, entry),
            HikvisionDoorSensor(coordinator, entry),
        ]
    )


def _device_info(coordinator: HikvisionCoordinator, entry: ConfigEntry) -> dict:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": coordinator.name,
        "manufacturer": "Hikvision",
        "model": "Access Controller",
        "configuration_url": f"https://{entry.data['host']}",
    }


class HikvisionLastEventActiveSensor(BinarySensorEntity):
    """Pulses ON when any event arrives; turns OFF automatically after a quiet period.

    Uses python-debouncer (trailing debounce) for the auto-reset:
    the sensor stays ON as long as events keep arriving, and only switches
    OFF once no new event has been received for BINARY_SENSOR_ACTIVE_SECONDS.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"
    _attr_translation_key = "last_event_active"

    def __init__(self, coordinator: HikvisionCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_event_active"
        self._attr_is_on = False
        self._attr_device_info = _device_info(coordinator, entry)
        self._unsub: Any = None
        # Populated in async_added_to_hass once the event loop is running
        self._schedule_reset: Any = None

    async def async_added_to_hass(self) -> None:
        """Register listener and create the per-instance debounced reset."""
        self._unsub = self._coordinator.add_listener(self._handle_update)

        # Create a fresh debounced coroutine per entity instance.
        # trailing=True  → fires AFTER the wait period of quiet
        # leading=False  → does NOT fire on the first call
        # Concretely: turns the sensor OFF once no new event arrives for
        # BINARY_SENSOR_ACTIVE_SECONDS seconds.
        @debounce(
            wait=BINARY_SENSOR_ACTIVE_SECONDS,
            options=DebounceOptions(trailing=True, leading=False),
        )
        async def _reset() -> None:
            self._attr_is_on = False
            self.async_write_ha_state()

        self._schedule_reset = _reset

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    @callback
    def _handle_update(self) -> None:
        if self._coordinator.last_event is None or self._schedule_reset is None:
            return
        # Turn ON immediately …
        self._attr_is_on = True
        self.async_write_ha_state()
        # … and (re-)schedule the debounced OFF.
        # Each new event resets the wait timer, so the sensor stays ON
        # as long as events keep arriving.
        asyncio.ensure_future(self._schedule_reset())


class HikvisionDoorSensor(BinarySensorEntity):
    """Real-time door contact state derived from the event stream.

    on  = door is open  (event 5_22)
    off = door is closed (event 5_21)
    unknown = no door event received since HA start
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_translation_key = "door"

    def __init__(self, coordinator: HikvisionCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_door"
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
