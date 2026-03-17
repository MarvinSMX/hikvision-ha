"""Hikvision Access Control integration."""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from homeassistant.components import webhook
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_NOTIFICATION_IP,
    CONF_NOTIFICATION_PORT,
    CONF_WEBHOOK_ID,
    DOMAIN,
    PLATFORMS,
    STREAM_STATUS_CONNECTED,
)
from .coordinator import HikvisionCoordinator

_LOGGER = logging.getLogger(__name__)

_CARD_URL = "/hikvision_access/hikvision-access-card.js"
_CARD_FILE = Path(__file__).parent / "www" / "hikvision-access-card.js"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the Lovelace card as a frontend resource (runs once on HA start)."""
    hass.http.register_static_path(_CARD_URL, str(_CARD_FILE), cache_headers=False)
    add_extra_js_url(hass, _CARD_URL)
    return True


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

    # --- Ensure a short-enough webhook_id ---
    # Hikvision's <url> field is limited to ~74 characters.
    # /api/webhook/ = 13 chars → max token = 61 chars.
    # secrets.token_hex(16) = 32 hex chars → URL = 45 chars (safe).
    # Regenerate if the saved token is too long (e.g. from a previous version).
    _MAX_TOKEN = 56  # 56 hex chars → 69-char URL, safely under the device limit
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if not webhook_id or len(webhook_id) > _MAX_TOKEN:
        webhook_id = secrets.token_hex(16)  # 32 hex chars
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id}
        )
        _LOGGER.info(
            "Hikvision [%s]: webhook token (re)generated: ...%s",
            entry.data.get("host"),
            webhook_id[-8:],
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
    # Use the notification IP/port from config entry (set during setup wizard).
    # This is the address the Hikvision device will POST events to.
    # Falls back to hass.config.api if not stored (older config entries).
    notification_ip = entry.data.get(CONF_NOTIFICATION_IP) or (
        hass.config.api.local_ip if hass.config.api else None
    )
    notification_port = entry.data.get(CONF_NOTIFICATION_PORT) or (
        hass.config.api.port if hass.config.api else 8123
    ) or 8123

    if notification_ip:
        ha_url = f"http://{notification_ip}:{notification_port}"
        _LOGGER.info(
            "Hikvision [%s]: configuring device push → %s/api/webhook/%s",
            entry.data.get("host"),
            ha_url,
            webhook_id,
        )
        configured = await hass.async_add_executor_job(
            coordinator.configure_device, ha_url, webhook_id
        )
        # Set status from the event loop — NOT from inside the executor thread
        if configured:
            coordinator._set_status(STREAM_STATUS_CONNECTED)  # noqa: SLF001
    else:
        _LOGGER.warning(
            "Hikvision [%s]: no notification IP configured — "
            "device push will not be set up automatically. "
            "Manually POST to http://<HA-IP>:8123/api/webhook/%s",
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
