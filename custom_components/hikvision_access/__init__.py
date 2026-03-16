"""Hikvision Access Control integration."""
from __future__ import annotations

import logging
import secrets

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import CONF_WEBHOOK_ID, DOMAIN, PLATFORMS
from .coordinator import HikvisionCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry.

    Order:
    1. Create coordinator
    2. Ensure a webhook_id exists (generate once, stored in entry.data)
    3. Register the HA webhook handler
    4. Set up entity platforms (entities register listeners)
    5. Start coordinator (no-op for push, but satisfies the interface)
    6. Configure the device to push to our webhook (best-effort)
    """
    hass.data.setdefault(DOMAIN, {})

    coordinator = HikvisionCoordinator(hass, dict(entry.data))
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # --- Ensure a stable webhook_id ---
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if not webhook_id:
        webhook_id = secrets.token_hex(32)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id}
        )

    # --- Register webhook ---
    webhook.async_register(
        hass,
        DOMAIN,
        coordinator.name,
        webhook_id,
        coordinator.async_handle_webhook,
        local_only=True,  # only accept requests from the local network
    )

    # --- Entities first so listeners are ready before any events arrive ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.start()

    # --- Configure device push (best-effort; logged but not fatal) ---
    try:
        ha_url = get_url(
            hass,
            allow_internal=True,
            allow_external=False,
            allow_ip=True,
            require_ssl=False,
        )
    except NoURLAvailableError:
        # Fallback: construct from the HA API binding
        local_ip = hass.config.api.local_ip if hass.config.api else "localhost"
        port = hass.config.api.port if hass.config.api else 8123
        ha_url = f"http://{local_ip}:{port}"
        _LOGGER.warning(
            "Hikvision [%s]: no internal URL configured in HA — using %s",
            entry.data.get("host"),
            ha_url,
        )

    await hass.async_add_executor_job(
        coordinator.configure_device, ha_url, webhook_id
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload: deregister webhook, stop coordinator, remove entities."""
    coordinator: HikvisionCoordinator | None = hass.data[DOMAIN].get(entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if coordinator:
        await coordinator.stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)

    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if webhook_id:
        webhook.async_unregister(hass, webhook_id)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
