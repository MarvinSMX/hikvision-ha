"""Image entity for the Hikvision Access Control integration.

Shows the last face image captured by the reader.  The image bytes are
extracted from the multipart push notification sent by the device.
If the device firmware does not include image data in the push payload
(common on older firmware), the entity remains unavailable.
"""
from __future__ import annotations

from datetime import datetime as dt

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HikvisionCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HikvisionCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HikvisionFaceImageEntity(coordinator, entry)])


class HikvisionFaceImageEntity(ImageEntity):
    """Shows the last face image received from the Hikvision reader."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_face"
    _attr_content_type = "image/jpeg"

    def __init__(
        self, coordinator: HikvisionCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator.hass)
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_last_face"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )
        self._unsub: callable | None = None

    # ------------------------------------------------------------------
    # HA lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.add_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _handle_coordinator_update(self) -> None:
        if self._coordinator.last_face_image is not None:
            self._attr_image_last_updated = self._coordinator.last_face_image_updated
        self.schedule_update_ha_state()

    async def async_image(self) -> bytes | None:
        return self._coordinator.last_face_image

    @property
    def image_last_updated(self) -> dt | None:
        return self._coordinator.last_face_image_updated
