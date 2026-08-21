"""Button platform for Xiaomi Cloud locate actions."""

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Xiaomi locate buttons."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    entities = []
    for imei, info in (coordinator.data or {}).items():
        entities.append(XiaomiLocateButton(hass, coordinator, imei, info))
        entities.append(XiaomiNoiseButton(hass, coordinator, imei, info))
        entities.append(XiaomiLostModeButton(hass, coordinator, imei, info))
        _LOGGER.debug("locate button for: %s", imei)
    if entities:
        async_add_entities(entities, True)


class XiaomiLocateButton(ButtonEntity, Entity):
    """Button to trigger a live locate for a tracked device."""

    _attr_has_entity_name = True
    _attr_translation_key = "locate"
    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_icon = "mdi:cellphone-marker"

    def __init__(self, hass, coordinator, imei, info) -> None:
        """Set up a locate button."""
        self._hass = hass
        self._unique_id = f"{imei}_locate"
        self._imei = imei
        self.coordinator = coordinator
        self._device_name = info.get("model") or "Xiaomi device"

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

    async def async_press(self):
        """Send the find/locate command for this device."""
        _LOGGER.debug("Locate button pressed for %s", self._imei)
        await self.coordinator._send_command(
            {"service": "find", "data": {"imei": self._imei}}
        )


class XiaomiLostModeButton(ButtonEntity, Entity):
    """Button to enable lost mode for a tracked device."""

    _attr_has_entity_name = True
    _attr_translation_key = "lost"
    _attr_icon = "mdi:cellphone-lock"

    def __init__(self, hass, coordinator, imei, info) -> None:
        """Set up a lost mode button."""
        self._hass = hass
        self._unique_id = f"{imei}_lost"
        self._imei = imei
        self.coordinator = coordinator
        self._device_name = info.get("model") or "Xiaomi device"

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

    async def async_press(self):
        """Send the lost mode command for this device."""
        content = self.coordinator.lost_content.get(self._imei, "")
        phone = self.coordinator.lost_phone
        notify = self.coordinator.lost_notify
        if not content or not phone:
            _LOGGER.error(
                "Lost mode is not configured for %s: set the message on the "
                "device text entity and the phone number in the integration "
                "options",
                self._imei,
            )
            return
        _LOGGER.debug("Lost mode button pressed for %s", self._imei)
        await self.coordinator._send_command(
            {
                "service": "lost",
                "data": {
                    "imei": self._imei,
                    "content": content,
                    "phone": phone,
                    "onlinenotify": notify,
                },
            }
        )


class XiaomiNoiseButton(ButtonEntity, Entity):
    """Button to make a tracked device play a sound."""

    _attr_has_entity_name = True
    _attr_translation_key = "noise"
    _attr_icon = "mdi:volume-high"

    def __init__(self, hass, coordinator, imei, info) -> None:
        """Set up a play sound button."""
        self._hass = hass
        self._unique_id = f"{imei}_noise"
        self._imei = imei
        self.coordinator = coordinator
        self._device_name = info.get("model") or "Xiaomi device"

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

    async def async_press(self):
        """Send the play sound command for this device."""
        _LOGGER.debug("Noise button pressed for %s", self._imei)
        await self.coordinator._send_command(
            {"service": "noise", "data": {"imei": self._imei}}
        )
