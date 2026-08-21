"""Data update coordinator for Xiaomi Cloud."""

import asyncio
import datetime
import logging
import secrets
import time

import aiohttp
from aiohttp.client_exceptions import ClientConnectorError
import async_timeout

from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    browser_cookie_header,
    browser_find_device_credentials,
    device_status_params,
    entity_data,
    lost_command_params,
    noise_command_params,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SYNC_MODE_QUERY = 0
SYNC_MODE_LOCATE = 2


class XiaomiCloudDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Xiaomi Cloud data API."""

    def __init__(
        self,
        hass,
        user,
        password,
        scan_interval,
        coordinate_type,
        service_token=None,
        user_id=None,
        credential_update_callback=None,
        lost_phone="",
        lost_notify=True,
        cookies="",
        entry_id="",
    ):
        """Initialize."""
        self._username = user
        self._password = password
        self._device_info = []
        self._scan_interval = scan_interval
        self._coordinate_type = coordinate_type
        self.service_data = None
        self.userId = user_id
        self._Service_Token = service_token
        self._credential_update_callback = credential_update_callback
        self._cookies_str = cookies
        self._csrf_token = secrets.token_hex(12)
        self.entry_id = entry_id
        self.lost_content = {}
        self.lost_phone = lost_phone
        self.lost_notify = lost_notify
        self.login_result = False
        self.service = None

        update_interval = datetime.timedelta(minutes=self._scan_interval)
        _LOGGER.debug("Data will be update every %s", update_interval)

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    def _set_credentials(self, service_token, user_id, cookies=None):
        """Store refreshed Find Device credentials."""
        self._Service_Token = service_token
        self.userId = user_id
        if cookies is not None:
            self._cookies_str = cookies
        if self._credential_update_callback is not None:
            self._credential_update_callback(service_token, user_id, cookies)

    def cookie_header(self):
        """Return a browser-like Cookie header for i.mi.com API calls."""
        return browser_cookie_header(
            self._cookies_str, self._Service_Token, self.userId, self._csrf_token
        )

    async def _async_refresh_credentials(self):
        """Refresh Find Device credentials with the stored account password."""
        if not self._username or not self._password:
            _LOGGER.warning(
                "Cannot refresh Xiaomi credentials: no account password stored"
            )
            return False
        session = async_create_clientsession(
            self.hass,
            auto_cleanup=False,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        try:
            credentials = await browser_find_device_credentials(
                session, self._username, self._password
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to refresh Xiaomi credentials: %s", err)
            return False
        finally:
            session.detach()
        if credentials is None:
            return False
        self._set_credentials(*credentials)
        return True

    async def _async_ensure_device_info(self, session):
        """Load devices, refreshing rejected stored credentials once."""
        if await self._get_device_info(session):
            return True
        if not await self._async_refresh_credentials():
            return False
        return await self._get_device_info(session)

    def _find_headers(self):
        return {
            "Cookie": f"userId={self.userId};serviceToken={self._Service_Token}",
            "Accept-Language": "zh-CN",
            "Referer": "https://i.mi.com/find",
        }

    @staticmethod
    def _timestamp():
        return int(time.time() * 1000)

    async def _get_device_info(self, session):
        url = "https://i.mi.com/find/v3/device/status/list"
        try:
            async with async_timeout.timeout(15):
                r = await session.get(
                    url,
                    headers=self._find_headers(),
                    params={"ts": self._timestamp()},
                )
            if r.status != 200:
                self.login_result = False
                _LOGGER.warning(
                    "Xiaomi Cloud device list failed HTTP %s "
                    "(user=%s, token=%s..., token length: %s)",
                    r.status,
                    self.userId,
                    (self._Service_Token or "")[:8],
                    len(self._Service_Token or ""),
                )
                return False

            response = await r.json(content_type=None)
            if response.get("result") != "ok":
                self.login_result = False
                _LOGGER.warning(
                    "Xiaomi Cloud device list failed: %s", str(response)[:300]
                )
                return False

            self._device_info = response["data"]["deviceList"]
            return True
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as err:
            _LOGGER.warning("Failed to get Xiaomi device list: %s", err)
            return False

    async def _request_device_status(self, session, device, sync_mode):
        url = "https://i.mi.com/find/v3/device/status"
        params = device_status_params(device, sync_mode, self._timestamp())
        async with async_timeout.timeout(15):
            response = await session.get(
                url,
                headers=self._find_headers(),
                params=params,
            )
        if response.status != 200:
            self.login_result = False
            _LOGGER.warning(
                "Xiaomi Cloud device status failed HTTP %s", response.status
            )
            return None

        result = await response.json(content_type=None)
        if result.get("result") != "ok":
            return None
        return result["data"]

    def _find_targets(self):
        locatable = [
            device
            for device in self._device_info
            if any(
                component.get("online") and 32 in component.get("supportCmds", [])
                for component in device.get("componentList", [])
            )
        ]
        if not self.service_data or not self.service_data.get("imei"):
            return locatable

        identifier = self.service_data["imei"]
        return [
            device
            for device in locatable
            if device.get("fid") == identifier
            or any(
                component.get("did") == identifier
                for component in device.get("componentList", [])
            )
        ]

    async def _send_find_device_command(self, session):
        """Send the locate command for the requested device(s)."""
        targets = self._find_targets()
        if not targets:
            return False

        success = True
        for device in targets:
            try:
                result = await self._request_device_status(session, device, SYNC_MODE_LOCATE)
            except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as err:
                _LOGGER.warning("Failed to locate Xiaomi device: %s", err)
                result = None
            success = result is not None and success
        return success

    def _clear_pending_command(self):
        """Discard a command after one execution attempt."""
        self.service = None
        self.service_data = None

    def _find_device(self, identifier):
        return next(
            (
                item
                for item in self._device_info
                if item.get("fid") == identifier
                or any(
                    component.get("did") == identifier
                    for component in item.get("componentList", [])
                )
            ),
            None,
        )

    async def _send_noise_command(self, session):
        if self.service_data is None:
            self._clear_pending_command()
            return False
        identifier = self.service_data["imei"]
        device = self._find_device(identifier)
        if device is None or not (data := noise_command_params(device, identifier)):
            _LOGGER.warning("Device does not support play sound: %s", identifier)
            self._clear_pending_command()
            return False
        data["serviceToken"] = self._Service_Token

        url = "https://i.mi.com/find/v2/device/command/send"
        try:
            async with async_timeout.timeout(15):
                response = await session.post(
                    url,
                    headers=self._find_headers(),
                    data=data,
                )
            result = await response.json(content_type=None)
            _LOGGER.debug("noise result: %s", result)
            if response.status == 200 and result.get("result") == "ok":
                self._clear_pending_command()
                return True
            _LOGGER.warning("Failed to play Xiaomi sound: %s", result)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Failed to play Xiaomi sound: %s", err)
        self._clear_pending_command()
        self.login_result = False
        return False

    async def _send_lost_command(self, session):
        if self.service_data is None:
            self._clear_pending_command()
            return False
        identifier = self.service_data["imei"]
        device = self._find_device(identifier)
        if device is None or not (
            data := lost_command_params(
                device,
                identifier,
                phone=self.service_data["phone"],
                content=self.service_data["content"],
                notify=self.service_data["onlinenotify"],
            )
        ):
            _LOGGER.warning("Device does not support lost mode: %s", identifier)
            self._clear_pending_command()
            return False
        data["serviceToken"] = self._Service_Token

        url = "https://i.mi.com/find/v2/device/command/send"
        try:
            async with async_timeout.timeout(15):
                response = await session.post(
                    url,
                    headers=self._find_headers(),
                    data=data,
                )
            result = await response.json(content_type=None)
            _LOGGER.debug("lost result: %s", result)
            if response.status == 200 and result.get("result") == "ok":
                self._clear_pending_command()
                return True
            _LOGGER.warning("Failed to enable Xiaomi lost mode: %s", result)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Failed to enable Xiaomi lost mode: %s", err)
        self._clear_pending_command()
        self.login_result = False
        return False

    async def _send_clipboard_command(self, session):
        if self.service_data is None:
            self._clear_pending_command()
            return False
        ok = await self.send_clipboard_text(self.service_data["text"])
        self._clear_pending_command()
        return ok

    async def send_clipboard_text(self, text):
        """Send text to the Xiaomi cloud clipboard, refreshing the token once."""
        if await self._post_clipboard_text(text):
            return True
        # The stored token may have expired; refresh it once and retry.
        if await self._async_refresh_credentials():
            self.login_result = True
            return await self._post_clipboard_text(text)
        return False

    async def _post_clipboard_text(self, text):
        if not self.userId or not self._Service_Token:
            _LOGGER.warning("No Xiaomi credentials available for clipboard")
            return False
        session = async_get_clientsession(self.hass)
        url = "https://i.mi.com/clipboard/lite/text"
        headers = {
            "Cookie": f"userId={self.userId};serviceToken={self._Service_Token}"
        }
        data = {"text": text, "serviceToken": self._Service_Token}
        try:
            async with async_timeout.timeout(15):
                r = await session.post(url, headers=headers, data=data)
            result = await r.json()
            _LOGGER.debug("clipboard res: %s", result)
            if r.status == 200 and result.get("code", 0) == 0:
                return True
            self.login_result = False
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Failed to send Xiaomi clipboard text: %s", err)
            self.login_result = False
        return False

    async def _send_command(self, data):
        self.service_data = data["data"]
        self.service = data["service"]
        await self.async_refresh()

    async def _get_device_location(self, session):
        """Query the last known location for every device."""
        devices_info = {}
        for device in self._device_info:
            result = None
            try:
                for attempt in range(3):
                    result = await self._request_device_status(
                        session, device, SYNC_MODE_QUERY
                    )
                    if result is None or not result.get("isLocating"):
                        break
                    if attempt < 2:
                        await asyncio.sleep(3)
            except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as err:
                _LOGGER.warning("Failed to update Xiaomi device status: %s", err)
                continue
            if result is None:
                continue

            info = entity_data(result, self._coordinate_type)
            if info is not None:
                devices_info[info["imei"]] = info
        if self.service == "find":
            self._clear_pending_command()
        return devices_info

    async def _refresh_locations(self, session):
        """Return fresh locations, keeping the last known data on failure."""
        locations = await self._get_device_location(session)
        if locations:
            return locations
        if self.data:
            _LOGGER.warning("No location data this cycle; keeping previous data")
            return self.data
        raise UpdateFailed("Failed to update Xiaomi Cloud location")

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("service: %s", self.service)
        try:
            session = async_get_clientsession(self.hass)
            if not self.login_result:
                if not await self._async_ensure_device_info(session):
                    raise UpdateFailed("Xiaomi Cloud login failed")
                self.login_result = True
                _LOGGER.info("get_device info succeed")

            service = self.service
            if service == "noise":
                ok = await self._send_noise_command(session)
            elif service == "lost":
                ok = await self._send_lost_command(session)
            elif service == "clipboard":
                ok = await self._send_clipboard_command(session)
            elif service == "find":
                ok = await self._send_find_device_command(session)
                if ok:
                    await asyncio.sleep(15)
                    return await self._refresh_locations(session)
                _LOGGER.warning("find command failed")
                return self.data or {}
            else:
                # Scheduled poll: only query status, never trigger a locate.
                return await self._refresh_locations(session)

            if not ok:
                _LOGGER.warning("command failed: %s", service)
                return self.data or {}
            await asyncio.sleep(5)
            return await self._refresh_locations(session)

        except ClientConnectorError as error:
            raise UpdateFailed(error) from error
