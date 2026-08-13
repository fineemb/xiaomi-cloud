"""Support for the Xiaomi device tracking."""
import logging

try:
    from homeassistant.components.device_tracker import SourceType, TrackerEntity
except ImportError:  # Older Home Assistant kept TrackerEntity in config_entry.
    from homeassistant.components.device_tracker import SourceType
    from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Xiaomi device tracker entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    devices = []
    for imei, info in (coordinator.data or {}).items():
        devices.append(XiaomiDeviceEntity(hass, coordinator, imei, info))
        _LOGGER.debug("device is: %s", imei)
    if devices:
        async_add_entities(devices, True)


class XiaomiDeviceEntity(TrackerEntity, RestoreEntity, Entity):
    """Represent a tracked device."""

    _attr_has_entity_name = True
    _attr_translation_key = "location"
    _attr_icon = "mdi:cellphone-android"

    def __init__(self, hass, coordinator, imei, info) -> None:
        """Set up a tracked device."""
        self._hass = hass
        self._unique_id = imei
        self.coordinator = coordinator
        self._device_name = info.get("model") or "Xiaomi device"
        self._attr_sw_version = info.get("version") or None

    def _device(self):
        return self.coordinator.data.get(self._unique_id, {}) or {}

    async def async_added_to_hass(self):
        """Subscribe for update from the coordinator."""
        _LOGGER.debug("device_tracker_unique_id: %s", self._unique_id)
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def battery_level(self):
        """Return battery value of the device."""
        return self._device().get("device_power")

    @property
    def extra_state_attributes(self):
        """Return device specific attributes."""
        data = self._device()
        return {
            "last_update": data.get("device_location_update_time"),
            "coordinate_type": data.get("coordinate_type"),
            "device_phone": data.get("device_phone"),
            "imei": self._unique_id,
        }

    @property
    def latitude(self):
        """Return latitude value of the device."""
        return self._device().get("device_lat")

    @property
    def longitude(self):
        """Return longitude value of the device."""
        return self._device().get("device_lon")

    @property
    def location_accuracy(self):
        """Return the gps accuracy of the device."""
        return self._device().get("device_accuracy")

    @property
    def unique_id(self):
        """Return the unique ID."""
        return self._unique_id

    @property
    def device_info(self):
        """Return the device info."""
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": self._device_name,
            "manufacturer": "Xiaomi",
            "sw_version": self._attr_sw_version,
            "model": self._device_name,
        }

    @property
    def should_poll(self):
        """Return the polling requirement of the entity."""
        return False

    @property
    def source_type(self):
        """Return the source type, eg gps or router, of the device."""
        return SourceType.GPS
