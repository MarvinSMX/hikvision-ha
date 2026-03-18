"""Camera entity: JPEG-Snapshot bei Zugangs-Events für Hikvision Face Terminals."""
from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_SNAPSHOTS, DOMAIN
from .coordinator import HikvisionCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    merged = {**entry.data, **entry.options}
    if not merged.get(CONF_ENABLE_SNAPSHOTS, True):
        return
    coordinator: HikvisionCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HikvisionSnapshotCamera(coordinator, entry)])


class HikvisionSnapshotCamera(Camera):
    """Zeigt den letzten JPEG-Snapshot bei Zugang gewährt/verweigert."""

    _attr_has_entity_name = True
    _attr_translation_key = "snapshot"
    _attr_icon = "mdi:camera"
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_is_streaming = False
    _attr_brand = "Hikvision"

    def __init__(
        self, coordinator: HikvisionCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_snapshot"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        self._unsub = self._coordinator.add_listener(
            lambda: self.schedule_update_ha_state()
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    @property
    def available(self) -> bool:
        return self._coordinator.last_snapshot is not None

    async def stream_source(self) -> str | None:
        """RTSP-URL für den Live-Stream."""
        return self._coordinator.rtsp_url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self._coordinator.last_snapshot
