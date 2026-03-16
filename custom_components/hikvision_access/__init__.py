"""Hikvision Access Control integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import HikvisionAcsPoller

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry: create poller, set up platforms, then start polling."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = HikvisionAcsPoller(hass, dict(entry.data))
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Platforms first → entities register their listeners before the first poll fires.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # start() loads persisted serial from storage and schedules the poll timer.
    await coordinator.start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry: stop polling, persist serial, remove entities."""
    coordinator: HikvisionAcsPoller | None = hass.data[DOMAIN].get(entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if coordinator:
        await coordinator.stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
