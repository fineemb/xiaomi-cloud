"""Config flow for Xiaomi Cloud."""

from collections import OrderedDict
import logging
import secrets
import time
import traceback

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    browser_cookie_header,
    browser_find_device_credentials,
    check_find_access,
    check_todo_access,
    config_entry_data,
)
from .const import (
    CONF_LOST_NOTIFY,
    CONF_LOST_PHONE,
    CONF_COORDINATE_TYPE,
    CONF_COORDINATE_TYPE_BAIDU,
    CONF_COORDINATE_TYPE_GOOGLE,
    CONF_COORDINATE_TYPE_ORIGINAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _parse_cookie_header(cookie_header: str) -> dict[str, str]:
    """Parse a Cookie header into a key/value map."""
    cookies = {}
    for part in cookie_header.split(";"):
        if "=" in part:
            key, _, value = part.strip().partition("=")
            cookies[key.strip()] = value.strip()
    return cookies


class XiaomiCloudlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Xiaomi Cloud."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return XiaomiCloudOptionsFlow()

    def __init__(self):
        """Initialize."""
        self._errors = {}
        self._user = None
        self._password = ""

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        self._errors = {}
        if user_input is None:
            return self._show_config_form()

        if user_input.get("manual_input"):
            self._user = str(user_input.get(CONF_USERNAME, "")).strip()
            self._password = str(user_input.get(CONF_PASSWORD, ""))
            return await self.async_step_manual()

        username = str(user_input.get(CONF_USERNAME, "")).strip()
        password = str(user_input.get(CONF_PASSWORD, ""))
        if not username or not password:
            self._errors["base"] = "login_url_failed"
            return self._show_config_form(user_input)

        existing = await self._check_existing(username)
        if existing:
            return self.async_abort(reason="already_configured")

        self._user = username
        self._password = password

        session = async_create_clientsession(
            self.hass,
            auto_cleanup=False,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        try:
            credentials = await browser_find_device_credentials(
                session, username, password
            )
            if credentials is None:
                _LOGGER.warning("Xiaomi browser password login failed")
                self._errors["base"] = "login_verification_required"
                return self._show_config_form(user_input)
            service_token, user_id, cookie_header = credentials

            if not await self._get_device_info(session, service_token, user_id):
                _LOGGER.warning("get_device info Failed")
                self._errors["base"] = "get_device_failed"
                return self._show_config_form(user_input)

            return self.async_create_entry(
                title=username,
                data=config_entry_data(
                    username, password, service_token, user_id, cookie_header
                ),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Login error: %s", err)
            self._errors["base"] = "login_url_failed"
            return self._show_config_form(user_input)
        finally:
            session.detach()

    async def async_step_manual(self, user_input=None):
        """Handle manual serviceToken / userId input."""
        self._errors = {}
        if user_input is None:
            return self._show_manual_form()

        cookie_header = str(user_input.get("cookies", "")).strip()
        service_token = str(user_input.get("serviceToken", "")).strip()
        user_id = str(user_input.get("userId", "")).strip()

        if cookie_header:
            extracted = _parse_cookie_header(cookie_header)
            service_token = extracted.get("serviceToken") or service_token
            user_id = extracted.get("userId") or user_id

        if not service_token or not user_id:
            self._errors["base"] = "manual_cookie_invalid"
            return self._show_manual_form()

        if not cookie_header:
            cookie_header = f"userId={user_id};serviceToken={service_token}"

        session = async_create_clientsession(self.hass)
        try:
            device_info = await self._get_device_info(
                session, service_token, user_id
            )
            todo_ok = await check_todo_access(
                session,
                browser_cookie_header(
                    cookie_header, service_token, user_id, secrets.token_hex(12)
                ),
            )
        finally:
            session.detach()

        if not device_info:
            _LOGGER.warning("Manual Xiaomi credentials are invalid")
            self._errors["base"] = "manual_cookie_invalid"
            return self._show_manual_form()

        if not todo_ok:
            _LOGGER.warning("Manual cookies cannot access the Xiaomi note API")
            self._errors["base"] = "manual_cookie_invalid"
            return self._show_manual_form()

        return self.async_create_entry(
            title=self._user or user_id,
            data={
                CONF_USERNAME: self._user or user_id,
                CONF_PASSWORD: self._password or "",
                "serviceToken": service_token,
                "userId": user_id,
                "cookies": cookie_header,
                "manual": True,
            },
        )

    async def _get_device_info(self, session, service_token, user_id):
        url = "https://i.mi.com/find/v3/device/status/list"
        headers = {
            "Cookie": f"userId={user_id};serviceToken={service_token}",
            "Accept-Language": "zh-CN",
            "Referer": "https://i.mi.com/find",
        }
        try:
            r = await session.get(
                url,
                headers=headers,
                params={"ts": int(time.time() * 1000)},
            )
            if r.status != 200:
                return False

            response = await r.json(content_type=None)
            if response.get("result") != "ok":
                return False
            return response["data"]["deviceList"]
        except (aiohttp.ClientError, KeyError, ValueError):
            _LOGGER.warning(traceback.format_exc())
            return False

    def _show_config_form(self, user_input=None):
        username = str((user_input or {}).get(CONF_USERNAME, "")).strip()
        data_schema = OrderedDict()
        data_schema[vol.Required(CONF_USERNAME, default=username)] = str
        data_schema[vol.Optional(CONF_PASSWORD)] = str
        data_schema[vol.Optional("manual_input", default=False)] = bool
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=self._errors,
        )

    def _show_manual_form(self):
        data_schema = vol.Schema(
            {
                vol.Optional("serviceToken", default=""): str,
                vol.Optional("userId", default=""): str,
                vol.Optional("cookies", default=""): str,
            }
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=data_schema,
            errors=self._errors,
        )

    async def async_step_import(self, user_input):
        """Import a config entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title="configuration.yaml", data={})

    async def _check_existing(self, username):
        for entry in self._async_current_entries():
            if username == entry.data.get(CONF_USERNAME):
                return True
        return False


class XiaomiCloudOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle the options step."""
        if user_input is None:
            return self._show_options_form()

        cookies = str(user_input.get("cookies", "")).strip()
        if cookies:
            parsed = _parse_cookie_header(cookies)
            user_id = parsed.get("userId") or self.config_entry.data.get("userId")
            service_token = parsed.get("serviceToken") or self.config_entry.data.get(
                "serviceToken"
            )
            if not user_id or not service_token:
                return self._show_options_form(errors={"base": "manual_cookie_invalid"})

            session = async_create_clientsession(self.hass)
            try:
                find_ok = await check_find_access(session, user_id, service_token)
                todo_ok = await check_todo_access(
                    session,
                    browser_cookie_header(
                        cookies, service_token, user_id, secrets.token_hex(12)
                    ),
                )
            finally:
                session.detach()

            if not find_ok and not todo_ok:
                _LOGGER.warning("Pasted cookies are invalid (find=%s, todo=%s)", find_ok, todo_ok)
                return self._show_options_form(errors={"base": "manual_cookie_invalid"})

            # Persist the session into the entry data so the coordinator
            # picks it up after the reload triggered by the options change.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    "cookies": cookies,
                    "serviceToken": service_token,
                    "userId": user_id,
                },
            )
            _LOGGER.info("Xiaomi Cloud cookies updated (find=%s, todo=%s)", find_ok, todo_ok)

        options_data = {
            key: value for key, value in user_input.items() if key != "cookies"
        }
        return self.async_create_entry(title="", data=options_data)

    def _show_options_form(self, errors=None):
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(CONF_SCAN_INTERVAL, 60),
                    ): int,
                    vol.Optional(
                        CONF_COORDINATE_TYPE,
                        default=self.config_entry.options.get(
                            CONF_COORDINATE_TYPE, CONF_COORDINATE_TYPE_ORIGINAL
                        ),
                    ): vol.In(
                        [
                            CONF_COORDINATE_TYPE_BAIDU,
                            CONF_COORDINATE_TYPE_GOOGLE,
                            CONF_COORDINATE_TYPE_ORIGINAL,
                        ]
                    ),
                    vol.Optional(
                        CONF_LOST_PHONE,
                        default=self.config_entry.options.get(CONF_LOST_PHONE, ""),
                    ): str,
                    vol.Optional(
                        CONF_LOST_NOTIFY,
                        default=self.config_entry.options.get(CONF_LOST_NOTIFY, True),
                    ): bool,
                    vol.Optional("cookies", default=""): str,
                }
            ),
            errors=errors or {},
        )
