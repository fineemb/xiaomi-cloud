"""Sensor platform for Xiaomi Cloud device attributes."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)

# (coordinator data key, translation key, icon)
SENSORS = (
    ("address", "address", "mdi:map-marker"),
    ("charging", "charging", "mdi:battery-charging"),
    ("status", "device_status", "mdi:cellphone"),
    ("lost_mode", "lost_mode", "mdi:cellphone-lock"),
    ("offline_find", "offline_find", "mdi:cellphone-off"),
    ("wipe", "wipe", "mdi:delete-alert"),
    ("share_location", "share_location", "mdi:share-variant"),
    ("support_sms", "support_sms", "mdi:message-text"),
)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Xiaomi device attribute sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    entities = []
    for imei, info in (coordinator.data or {}).items():
        for data_key, translation_key, icon in SENSORS:
            entities.append(
                XiaomiDeviceSensor(
                    hass,
                    coordinator,
                    imei,
                    info,
                    data_key,
                    translation_key,
                    icon,
                )
            )
        _LOGGER.debug("sensors for: %s", imei)
    if entities:
        async_add_entities(entities, True)


class XiaomiDeviceSensor(SensorEntity, Entity):
    """Sensor exposing a single attribute of a tracked device."""

    _attr_has_entity_name = True

    def __init__(
        self, hass, coordinator, imei, info, data_key, translation_key, icon
    ) -> None:
        """Set up a device attribute sensor."""
        self._hass = hass
        self._unique_id = f"{imei}_{translation_key}"
        self._imei = imei
        self.coordinator = coordinator
        self._data_key = data_key
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._device_name = info.get("model") or "Xiaomi device"

    def _device(self):
        return self.coordinator.data.get(self._imei, {}) or {}

    def _format(self, value):
        if self._data_key == "charging":
            return "charging" if value else "not_charging"
        if value is True:
            return "on"
        if value is False:
            return "off"
        if value == "enable":
            return "enabled"
        if value == "disable":
            return "disabled"
        return value

    @property
    def available(self):
        """Return True if the coordinator is healthy."""
        return self.coordinator.last_update_success

    @property
    def unique_id(self):
        """Return the unique ID."""
        return self._unique_id

    @property
    def device_info(self):
        """Return the device info, grouped with the tracker entity."""
        return {
            "identifiers": {(DOMAIN, self._imei)},
            "via_device": (DOMAIN, f"account_{self.coordinator.entry_id}"),
            "name": self._device_name,
            "manufacturer": "Xiaomi",
            "model": self._device_name,
        }

    @property
    def native_value(self):
        """Return the sensor state."""
        value = self._device().get(self._data_key)
        if self._data_key == "address" and not value:
            return None
        return self._format(value)

    @property
    def extra_state_attributes(self):
        """Return extra attributes for the address sensor."""
        if self._data_key != "address":
            return {}
        data = self._device()
        return {
            "address_component": data.get("address_component", ""),
            "source_type": data.get("source_type", ""),
            "accuracy": data.get("device_accuracy"),
            "coordinate_type": data.get("coordinate_type"),
            "last_update": data.get("device_location_update_time"),
        }

    async def async_added_to_hass(self):
        """Subscribe for update from the coordinator."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
