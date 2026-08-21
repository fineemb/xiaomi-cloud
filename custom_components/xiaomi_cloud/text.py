"""Text platform for the Xiaomi Cloud clipboard."""

import logging

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from .const import CONF_LOST_CONTENT, COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Xiaomi cloud clipboard text entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    lost_content_seed = config_entry.options.get(CONF_LOST_CONTENT, "")
    entities = [XiaomiClipboardText(hass, coordinator, config_entry)]
    for imei, info in (coordinator.data or {}).items():
        entities.append(
            XiaomiLostMessageText(
                hass, coordinator, imei, info, initial_value=lost_content_seed
            )
        )
        _LOGGER.debug("lost message text entity for: %s", imei)
    async_add_entities(entities, True)


class XiaomiClipboardText(TextEntity, Entity):
    """Text input that sends its content to the Xiaomi cloud clipboard."""

    _attr_has_entity_name = True
    _attr_translation_key = "clipboard"
    _attr_icon = "mdi:clipboard-text-outline"
    _attr_native_min = 0
    _attr_native_max = 500
    # Recent Home Assistant renamed TextEntityMode to TextMode and
    # native_mode to mode; set both so either version is supported.
    _attr_mode = "text"
    _attr_native_mode = "text"

    def __init__(self, hass, coordinator, config_entry) -> None:
        """Set up the account-level clipboard text entity."""
        self._hass = hass
        self._entry_id = config_entry.entry_id
        self._unique_id = f"account_{config_entry.entry_id}_clipboard"
        self.coordinator = coordinator
        self._account_name = coordinator._username or "Xiaomi Cloud"
        self._attr_native_value = ""

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
        """Return the account-level device info."""
        return {
            "identifiers": {(DOMAIN, f"account_{self._entry_id}")},
            "name": self._account_name,
            "manufacturer": "Xiaomi",
            "model": "Xiaomi Cloud",
        }

    async def async_set_value(self, value: str):
        """Send the entered text to the cloud clipboard."""
        value = value or ""
        if not value:
            self._attr_native_value = ""
            self.async_write_ha_state()
            return

        _LOGGER.debug("Sending clipboard text for %s", self._account_name)
        if await self.coordinator.send_clipboard_text(value):
            # Clear the input after a successful send.
            self._attr_native_value = ""
        else:
            # Keep the text so the user can retry.
            self._attr_native_value = value
        self.async_write_ha_state()


class XiaomiLostMessageText(TextEntity, Entity):
    """Text input holding the message used when enabling lost mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "lost_message"
    _attr_icon = "mdi:message-text-lock"
    _attr_native_min = 0
    _attr_native_max = 500
    # Recent Home Assistant renamed TextEntityMode to TextMode and
    # native_mode to mode; set both so either version is supported.
    _attr_mode = "text"
    _attr_native_mode = "text"

    def __init__(self, hass, coordinator, imei, info, *, initial_value="") -> None:
        """Set up a lost mode message text entity."""
        self._hass = hass
        self._unique_id = f"{imei}_lost_message"
        self._imei = imei
        self.coordinator = coordinator
        self._device_name = info.get("model") or "Xiaomi device"
        self._attr_native_value = initial_value
        coordinator.lost_content[imei] = initial_value

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

    async def async_set_value(self, value: str):
        """Store the message for the lost mode button to use."""
        value = value or ""
        self.coordinator.lost_content[self._imei] = value
        self._attr_native_value = value
        self.async_write_ha_state()
