"""Hikvision Access Control integration."""
from __future__ import annotations

import logging
import secrets

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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
    # local_only=False: the Hikvision device may be on a different subnet
    # (e.g. 10.69.x) from HA (192.168.x), or may reach HA via an external
    # domain.  The random webhook token already provides security.
    webhook.async_register(
        hass,
        DOMAIN,
        coordinator.name,
        webhook_id,
        coordinator.async_handle_webhook,
    )

    # --- Entities first so listeners are ready before any events arrive ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.start()

    # --- Configure device push (best-effort; logged but not fatal) ---
    # Hikvision devices send HTTP POST to a plain HTTP endpoint on the local
    # network — they cannot validate HTTPS certificates from reverse proxies
    # or external domains.  We therefore ALWAYS use the HA local IP + HTTP,
    # regardless of how HA is accessed from the outside.
    # This matches every known working reference implementation (e.g.
    # https://github.com/hab1b/Redsis_Hikvision_HTTP_Listener).
    if hass.config.api:
        local_ip = hass.config.api.local_ip
        local_port = hass.config.api.port or 8123
        uses_ssl = getattr(hass.config.api, "use_ssl", False)

        if uses_ssl:
            _LOGGER.warning(
                "Hikvision [%s]: HA is running with native SSL on port %d. "
                "The Hikvision device sends plain HTTP and cannot validate "
                "self-signed certificates. Configure a reverse proxy that "
                "accepts HTTP from the device's subnet, or disable native SSL "
                "and use a reverse proxy for external HTTPS instead.",
                entry.data.get("host"),
                local_port,
            )

        ha_url = f"http://{local_ip}:{local_port}"
        _LOGGER.info(
            "Hikvision [%s]: configuring device push → %s/api/webhook/%s",
            entry.data.get("host"),
            ha_url,
            webhook_id,
        )
        await hass.async_add_executor_job(
            coordinator.configure_device, ha_url, webhook_id
        )
    else:
        _LOGGER.warning(
            "Hikvision [%s]: could not determine HA local IP — "
            "device push notification will not be configured automatically. "
            "Manually configure the device to POST to "
            "http://<HA-IP>:8123/api/webhook/%s",
            entry.data.get("host"),
            webhook_id,
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
