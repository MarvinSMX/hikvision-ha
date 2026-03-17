"""Switch entity: Zugangssperre für Hikvision Face Terminals."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CMD_LOCK, CMD_UNLOCK, DOMAIN
from .coordinator import HikvisionCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HikvisionCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HikvisionAccessLockSwitch(coordinator, entry)])


class HikvisionAccessLockSwitch(SwitchEntity):
    """Schalter: ON = Zugang dauerhaft gesperrt, OFF = Normalbetrieb."""

    _attr_has_entity_name = True
    _attr_translation_key = "access_lock"
    _attr_icon = "mdi:door-closed-lock"

    def __init__(
        self, coordinator: HikvisionCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_access_lock"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._is_on = False
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    def _handle_update(self) -> None:
        self.schedule_update_ha_state()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Zugang sperren — alwaysClose."""
        ok = await self.hass.async_add_executor_job(
            self._coordinator.remote_control, CMD_LOCK
        )
        if ok:
            self._is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Normalbetrieb wiederherstellen — close."""
        ok = await self.hass.async_add_executor_job(
            self._coordinator.remote_control, CMD_UNLOCK
        )
        if ok:
            self._is_on = False
            self.async_write_ha_state()
