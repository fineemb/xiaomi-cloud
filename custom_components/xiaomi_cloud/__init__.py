"""
Component to integrate with xiaomi cloud.

For more details about this component, please refer to
https://github.com/fineemb/xiaomi-cloud
"""
import logging

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.text import DOMAIN as TEXT_DOMAIN
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_LOST_NOTIFY,
    CONF_LOST_PHONE,
    CONF_COORDINATE_TYPE,
    CONF_COORDINATE_TYPE_ORIGINAL,
    COORDINATOR,
    DOMAIN,
    UNDO_UPDATE_LISTENER,
)
from .data_update_coordinator import XiaomiCloudDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up configured xiaomi cloud."""
    hass.data[DOMAIN] = {"devices": set(), "unsub_device_tracker": {}}
    return True


async def async_setup_entry(hass, config_entry) -> bool:
    """Set up xiaomi cloud as config entry."""
    username = config_entry.data.get(CONF_USERNAME)
    password = config_entry.data.get(CONF_PASSWORD, "")
    scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, 60)
    coordinate_type = config_entry.options.get(
        CONF_COORDINATE_TYPE, CONF_COORDINATE_TYPE_ORIGINAL
    )

    _LOGGER.debug("Username: %s", username)

    def update_credentials(service_token, user_id, cookies=None):
        """Persist refreshed Xiaomi Find Device credentials."""
        try:
            data = {
                **config_entry.data,
                "serviceToken": service_token,
                "userId": user_id,
            }
            if cookies is not None:
                data["cookies"] = cookies
            hass.config_entries.async_update_entry(
                config_entry,
                data=data,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to persist Xiaomi credentials: %s", err)

    coordinator = XiaomiCloudDataUpdateCoordinator(
        hass,
        username,
        password,
        scan_interval,
        coordinate_type,
        service_token=config_entry.data.get("serviceToken"),
        user_id=config_entry.data.get("userId"),
        credential_update_callback=update_credentials,
        lost_phone=config_entry.options.get(CONF_LOST_PHONE, ""),
        lost_notify=config_entry.options.get(CONF_LOST_NOTIFY, True),
        cookies=config_entry.data.get("cookies"),
        entry_id=config_entry.entry_id,
    )
    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    undo_listener = config_entry.add_update_listener(update_listener)

    hass.data[DOMAIN][config_entry.entry_id] = {
        COORDINATOR: coordinator,
        UNDO_UPDATE_LISTENER: undo_listener,
    }
    await hass.config_entries.async_forward_entry_setups(
        config_entry,
        [DEVICE_TRACKER, BUTTON_DOMAIN, TEXT_DOMAIN, SENSOR_DOMAIN, TODO_DOMAIN],
    )

    # Only register the services once, regardless of how many entries exist.
    if not hass.services.has_service(DOMAIN, "noise"):

        async def services(call):
            """Handle the service call."""
            imei = call.data.get("imei")
            service = call.service

            target_coordinator = None
            for entry_id, entry_data in hass.data[DOMAIN].items():
                if entry_id in ("devices", "unsub_device_tracker"):
                    continue
                coord = entry_data[COORDINATOR]
                devices = coord.data or {}
                if imei in devices:
                    target_coordinator = coord
                    break

            if target_coordinator is None:
                _LOGGER.error(
                    "No coordinator found for device with IMEI: %s", imei
                )
                return

            if service == "noise":
                await target_coordinator._send_command(
                    {"service": "noise", "data": {"imei": imei}}
                )
            elif service == "find":
                await target_coordinator._send_command(
                    {"service": "find", "data": {"imei": imei}}
                )
            elif service == "lost":
                await target_coordinator._send_command(
                    {
                        "service": "lost",
                        "data": {
                            "imei": imei,
                            "content": call.data.get("content"),
                            "phone": call.data.get("phone"),
                            "onlinenotify": call.data.get("onlinenotify"),
                        },
                    }
                )
            elif service == "clipboard":
                await target_coordinator._send_command(
                    {
                        "service": "clipboard",
                        "data": {"text": call.data.get("text")},
                    }
                )

        hass.services.async_register(DOMAIN, "noise", services)
        hass.services.async_register(DOMAIN, "find", services)
        hass.services.async_register(DOMAIN, "lost", services)
        hass.services.async_register(DOMAIN, "clipboard", services)

    return True


async def async_unload_entry(hass, config_entry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(
        config_entry, DEVICE_TRACKER
    )
    unload_ok = (
        await hass.config_entries.async_forward_entry_unload(
            config_entry, BUTTON_DOMAIN
        )
        and unload_ok
    )
    unload_ok = (
        await hass.config_entries.async_forward_entry_unload(
            config_entry, TEXT_DOMAIN
        )
        and unload_ok
    )
    unload_ok = (
        await hass.config_entries.async_forward_entry_unload(
            config_entry, SENSOR_DOMAIN
        )
        and unload_ok
    )
    unload_ok = (
        await hass.config_entries.async_forward_entry_unload(
            config_entry, TODO_DOMAIN
        )
        and unload_ok
    )

    hass.data[DOMAIN][config_entry.entry_id][UNDO_UPDATE_LISTENER]()

    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)

        remaining_entries = [
            entry_id
            for entry_id in hass.data[DOMAIN]
            if entry_id not in ("devices", "unsub_device_tracker")
        ]
        if not remaining_entries:
            hass.services.async_remove(DOMAIN, "noise")
            hass.services.async_remove(DOMAIN, "find")
            hass.services.async_remove(DOMAIN, "lost")
            hass.services.async_remove(DOMAIN, "clipboard")

    return unload_ok


async def update_listener(hass, config_entry):
    """Update listener."""
    await hass.config_entries.async_reload(config_entry.entry_id)
