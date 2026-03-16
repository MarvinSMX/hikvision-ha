"""Hikvision Access Control integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import HikvisionStreamCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry: create coordinator and start the stream."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = HikvisionStreamCoordinator(hass, dict(entry.data))
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Start the blocking stream reader in a daemon thread
    await hass.async_add_executor_job(coordinator.start)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry: stop the stream and remove entities."""
    coordinator: HikvisionStreamCoordinator = hass.data[DOMAIN].get(entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if coordinator:
        await hass.async_add_executor_job(coordinator.stop)
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (options flow not implemented yet)."""
    await hass.config_entries.async_reload(entry.entry_id)
