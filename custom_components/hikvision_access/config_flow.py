"""Config flow for Hikvision Access Control."""
from __future__ import annotations

import logging
from typing import Any
import xml.etree.ElementTree as ET
import warnings

import requests
from requests.auth import HTTPDigestAuth
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ACS_CAPS_PATH,
    CONF_ENABLE_SNAPSHOTS,
    CONF_HOST,
    CONF_NAME,
    CONF_NOTIFICATION_IP,
    CONF_NOTIFICATION_PORT,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEVICE_INFO_PATH,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_VERIFY_SSL, default=False): bool,
    }
)

_ISAPI_NS = "http://www.isapi.org/ver20/XMLSchema"


def _connect_and_detect(
    host: str, username: str, password: str, verify_ssl: bool
) -> tuple[str | None, str | None]:
    """Validate credentials and detect the device name."""
    auth = HTTPDigestAuth(username, password)

    caps_url = f"https://{host}{ACS_CAPS_PATH}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(caps_url, auth=auth, verify=verify_ssl, timeout=10)
        if resp.status_code == 401:
            return "invalid_auth", None
        if resp.status_code != 200:
            return "cannot_connect", None
    except requests.exceptions.SSLError:
        return "ssl_error", None
    except requests.exceptions.ConnectionError:
        return "cannot_connect", None
    except requests.exceptions.Timeout:
        return "timeout", None
    except Exception:  # noqa: BLE001
        return "unknown", None

    info_url = f"https://{host}{DEVICE_INFO_PATH}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(info_url, auth=auth, verify=verify_ssl, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            for tag in (f"{{{_ISAPI_NS}}}deviceName", "deviceName"):
                elem = root.find(tag)
                if elem is not None and elem.text:
                    return None, elem.text.strip()
    except Exception:  # noqa: BLE001
        pass

    return None, None


async def _async_connect_and_detect(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[dict[str, str], str | None]:
    """Run _connect_and_detect in an executor."""
    error, name = await hass.async_add_executor_job(
        _connect_and_detect,
        data[CONF_HOST],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data.get(CONF_VERIFY_SSL, False),
    )
    errors = {"base": error} if error else {}
    return errors, name


class HikvisionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hikvision Access Control."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, Any] = {}
        self._detected_name: str = ""
        self._ha_local_ip: str = ""
        self._ha_local_port: int = 8123

    # ------------------------------------------------------------------
    # Step 1 – credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect host + credentials, validate, auto-detect device name."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            errors, detected = await _async_connect_and_detect(self.hass, user_input)

            if not errors:
                self._credentials = user_input
                self._detected_name = detected or user_input[CONF_HOST]

                # Pre-fill HA's local IP/port for the notification step
                if self.hass.config.api:
                    self._ha_local_ip = self.hass.config.api.local_ip or ""
                    self._ha_local_port = self.hass.config.api.port or 8123

                return await self.async_step_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 – confirm name + HA notification address
    # ------------------------------------------------------------------

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm device name and set the HA address the device will POST to."""
        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip() or self._detected_name
            entry_data = {
                **self._credentials,
                CONF_NAME: name,
                CONF_NOTIFICATION_IP: user_input.get(
                    CONF_NOTIFICATION_IP, self._ha_local_ip
                ),
                CONF_NOTIFICATION_PORT: int(
                    user_input.get(CONF_NOTIFICATION_PORT, self._ha_local_port)
                ),
                CONF_ENABLE_SNAPSHOTS: user_input.get(CONF_ENABLE_SNAPSHOTS, True),
            }
            return self.async_create_entry(title=name, data=entry_data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=self._detected_name): str,
                vol.Required(
                    CONF_NOTIFICATION_IP,
                    default=self._ha_local_ip,
                    description={"suggested_value": self._ha_local_ip},
                ): str,
                vol.Required(
                    CONF_NOTIFICATION_PORT,
                    default=self._ha_local_port,
                ): int,
                vol.Optional(CONF_ENABLE_SNAPSHOTS, default=True): bool,
            }
        )

        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            description_placeholders={"detected_name": self._detected_name},
        )
