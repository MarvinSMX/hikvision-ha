"""Binary sensor entities for Hikvision Access Control."""
from __future__ import annotations

import asyncio
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
    async_add_entities([HikvisionLastEventActiveSensor(coordinator, entry)])


class HikvisionLastEventActiveSensor(BinarySensorEntity):
    """Binary sensor that goes ON for a few seconds when any event arrives."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"

    def __init__(
        self,
        coordinator: HikvisionStreamCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_event_active"
        self._attr_name = f"{coordinator.name} Event Active"
        self._attr_is_on = False
        self._reset_task: Any = None
        self._unsub: Any = None

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": coordinator.name,
            "manufacturer": "Hikvision",
            "model": "Access Controller",
            "configuration_url": f"https://{entry.data['host']}",
        }

    async def async_added_to_hass(self) -> None:
        """Register coordinator listener."""
        self._unsub = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up listener and any pending reset task."""
        if self._unsub:
            self._unsub()
        if self._reset_task:
            self._reset_task()

    @callback
    def _handle_update(self) -> None:
        """Called by the coordinator when a new event arrives."""
        if self._coordinator.last_event is None:
            return

        # Turn on
        self._attr_is_on = True
        self.async_write_ha_state()

        # Cancel any pending auto-reset
        if self._reset_task:
            self._reset_task()

        # Schedule auto-reset
        self._reset_task = async_call_later(
            self.hass,
            BINARY_SENSOR_ACTIVE_SECONDS,
            self._async_reset,
        )

    @callback
    def _async_reset(self, _now: Any = None) -> None:
        """Turn the sensor off again after the timeout."""
        self._attr_is_on = False
        self._reset_task = None
        self.async_write_ha_state()
