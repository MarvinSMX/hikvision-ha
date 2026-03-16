"""Config flow for Hikvision Access Control."""
from __future__ import annotations

import json
import logging
from typing import Any

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
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    STREAM_PATH,
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


def _connect_and_detect(
    host: str, username: str, password: str, verify_ssl: bool
) -> tuple[str | None, str | None]:
    """Connect to the alertStream, verify auth, and try to read the first deviceName.

    Returns (error_key_or_None, detected_name_or_None).
    The read timeout is intentionally short (3 s); devices typically flush
    buffered events immediately on connect so this almost always succeeds.
    """
    url = f"https://{host}{STREAM_PATH}"
    try:
        with requests.get(
            url,
            auth=HTTPDigestAuth(username, password),
            stream=True,
            verify=verify_ssl,
            timeout=(10, 3),  # connect 10 s, read 3 s
        ) as resp:
            if resp.status_code == 401:
                return "invalid_auth", None
            if resp.status_code != 200:
                return "cannot_connect", None

            # Try to read enough data to find the first JSON part
            buffer = b""
            for chunk in resp.iter_content(chunk_size=4096):
                buffer += chunk
                name = _extract_first_device_name(buffer)
                if name:
                    return None, name
                # Stop after 32 KB – more than enough for several events
                if len(buffer) > 32768:
                    break

    except requests.exceptions.SSLError:
        return "ssl_error", None
    except requests.exceptions.ConnectionError:
        return "cannot_connect", None
    except requests.exceptions.Timeout:
        # Timeout on read means auth was fine but no events arrived yet –
        # treat as success with no detected name
        return None, None
    except Exception:  # noqa: BLE001
        return "unknown", None

    return None, None


def _extract_first_device_name(buffer: bytes) -> str | None:
    """Scan a raw stream buffer for the first AccessControllerEvent.deviceName."""
    sep = b"--MIME_boundary"
    start = 0
    while True:
        first = buffer.find(sep, start)
        if first == -1:
            break
        second = buffer.find(sep, first + len(sep))
        if second == -1:
            break

        part = buffer[first + len(sep) : second].strip()

        # Split headers / body
        for marker in (b"\r\n\r\n", b"\n\n"):
            if marker in part:
                _, body = part.split(marker, 1)
                body = body.strip()
                if body.startswith(b"{"):
                    try:
                        payload = json.loads(body)
                        ace = payload.get("AccessControllerEvent", {})
                        name = ace.get("deviceName", "").strip()
                        if name:
                            return name
                    except json.JSONDecodeError:
                        pass
                break

        start = second

    return None


async def _async_connect_and_detect(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[dict[str, str], str | None]:
    """Run _connect_and_detect in an executor. Returns (errors, detected_name)."""
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
                # Fall back to host if stream had no events within the read window
                self._detected_name = detected or user_input[CONF_HOST]
                return await self.async_step_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 – confirm / edit name
    # ------------------------------------------------------------------

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user confirm or override the auto-detected device name."""
        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip() or self._detected_name
            entry_data = {**self._credentials, CONF_NAME: name}
            return self.async_create_entry(title=name, data=entry_data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=self._detected_name): str,
            }
        )

        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            description_placeholders={"detected_name": self._detected_name},
        )
