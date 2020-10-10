
"""Adds config flow for Colorfulclouds."""
import logging
import json
import time
import re
import base64
import hashlib
import voluptuous as vol
from urllib import parse
import async_timeout
from collections import OrderedDict
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME

from homeassistant import config_entries, core, exceptions
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_USERNAME,
)

from .const import (
    CONF_WAKE_ON_START,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WAKE_ON_START,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    CONF_COORDINATE_TYPE,
    CONF_COORDINATE_TYPE_BAIDU,
    CONF_COORDINATE_TYPE_ORIGINAL,
    CONF_COORDINATE_TYPE_GOOGLE
)



_LOGGER = logging.getLogger(__name__)

@config_entries.HANDLERS.register(DOMAIN)
class XiaomiCloudlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return XiaomiCloudOptionsFlow(config_entry)

    def __init__(self):
        """Initialize."""
        self._errors = {}
        self.login_result = False
        self._user = None
        self._password = None
        self._headers = {}
        self._cookies = {}
        self._serviceLoginAuth2_json = {}
        self._sign = None

    async def async_step_user(self, user_input={}):
        self._errors = {}
        if user_input is not None:
            # Check if entered host is already in HomeAssistant
            existing = await self._check_existing(user_input[CONF_USERNAME])
            if existing:
                return self.async_abort(reason="already_configured")

            # If it is not, continue with communication test
            self._user = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            url = 'https://account.xiaomi.com/pass/serviceLogin?sid%3Di.mi.com&sid=i.mi.com&_locale=zh_CN&_snsNone=true'
            pattern = re.compile(r'_sign":"(.*?)",')
            
            try:
                
                session = async_get_clientsession(self.hass)
                session.cookie_jar.clear()
                tmp = await self._get_sign(session)
                if not tmp:
                    _LOGGER.warning("get_sign Failed")
                    self._errors["base"] = "get_sign_failed"
                    return await self._show_config_form(user_input)
                else:
                    tmp = await self._serviceLoginAuth2(session)
                    _LOGGER.debug("_serviceLoginAuth2: %s", tmp)
                    if not tmp:
                        _LOGGER.warning('Request Login_url Failed')
                        self._errors["base"] = "login_url_failed"
                        return await self._show_config_form(user_input)
                    else:
                        if self._serviceLoginAuth2_json['code'] == 0:
                            # logon success,run self._login_miai()
                            tmp = await self._login_miai(session)
                            if not tmp:
                                _LOGGER.warning('login Mi Cloud Failed')
                                self._errors["base"] = "login_mi_cloud_failed"
                                return await self._show_config_form(user_input)
                            else:
                                tmp = await self._get_device_info(session)
                                if not tmp:
                                    _LOGGER.warning('get_device info Failed')
                                    self._errors["base"] = "get_device_failed"
                                    return await self._show_config_form(user_input)
                                else:
                                    return self.async_create_entry(
                                        title=user_input[CONF_USERNAME], data=user_input
                                    )
                return True
            except BaseException as e:
                _LOGGER.warning(e.args[0])
                return False
            return await self._show_config_form(user_input)
        return await self._show_config_form(user_input)
    async def _get_sign(self, session):
        url = 'https://account.xiaomi.com/pass/serviceLogin?sid%3Di.mi.com&sid=i.mi.com&_locale=zh_CN&_snsNone=true'
        pattern = re.compile(r'_sign":"(.*?)",')
        
        try:
            with async_timeout.timeout(15, loop=self.hass.loop):
                r = await session.get(url, headers=self._headers)
            self._cookies['pass_trace'] = r.headers.getall('Set-Cookie')[2].split(";")[0].split("=")[1]
            self._sign = pattern.findall(await r.text())[0]
            return True
        except BaseException as e:
            _LOGGER.warning(e.args[0])
            return False

    async def _serviceLoginAuth2(self, session, captCode=None):
        url = 'https://account.xiaomi.com/pass/serviceLoginAuth2'
        self._headers['Content-Type'] = 'application/x-www-form-urlencoded'
        self._headers['Accept'] = '*/*'
        self._headers['Origin'] = 'https://account.xiaomi.com'
        self._headers[
            'Referer'] = 'https://account.xiaomi.com/pass/serviceLogin?sid%3Di.mi.com&sid=i.mi.com&_locale=zh_CN&_snsNone=true'
        self._headers['Cookie'] = 'pass_trace={};'.format(
            self._cookies['pass_trace'])

        auth_post_data = {'_json': 'true',
                          '_sign': self._sign,
                          'callback': 'https://i.mi.com/sts',
                          'hash': hashlib.md5(self._password.encode('utf-8')).hexdigest().upper(),
                          'qs': '%3Fsid%253Di.mi.com%26sid%3Di.mi.com%26_locale%3Dzh_CN%26_snsNone%3Dtrue',
                          'serviceParam': '{"checkSafePhone":false}',
                          'sid': 'i.mi.com',
                          'user': self._user}
        try:
            if captCode != None:
                url = 'https://account.xiaomi.com/pass/serviceLoginAuth2?_dc={}'.format(
                    int(round(time.time() * 1000)))
                auth_post_data['captCode'] = captCode
                self._headers['Cookie'] = self._headers['Cookie'] + \
                                          '; ick={}'.format(self._cookies['ick'])
            with async_timeout.timeout(15, loop=self.hass.loop):
                r = await session.post(url, headers=self._headers, data=auth_post_data, cookies=self._cookies)
            self._cookies['pwdToken'] = r.cookies.get('passToken').value
            self._serviceLoginAuth2_json = json.loads((await r.text())[11:])
            _LOGGER.debug("_serviceLoginAuth2_json: %s", self._serviceLoginAuth2_json['ssecurity'])
            return True
        except BaseException as e:
            _LOGGER.warning(e.args[0])
            return False

    async def _login_miai(self, session):
        serviceToken = "nonce={}&{}".format(
            self._serviceLoginAuth2_json['nonce'], self._serviceLoginAuth2_json['ssecurity'])
        serviceToken_sha1 = hashlib.sha1(serviceToken.encode('utf-8')).digest()
        base64_serviceToken = base64.b64encode(serviceToken_sha1)
        loginmiai_header = {'User-Agent': 'MISoundBox/1.4.0,iosPassportSDK/iOS-3.2.7 iOS/11.2.5',
                            'Accept-Language': 'zh-cn', 'Connection': 'keep-alive'}
        url = self._serviceLoginAuth2_json['location'] + \
              "&clientSign=" + parse.quote(base64_serviceToken.decode())
        try:
            with async_timeout.timeout(15, loop=self.hass.loop):
                r = await session.get(url, headers=loginmiai_header)
            if r.status == 200:
                self._Service_Token = r.cookies.get('serviceToken').value
                self.userId = r.cookies.get('userId').value
                return True
            else:
                return False
        except BaseException as e:
            _LOGGER.warning(e.args[0])
            return False

    async def _get_device_info(self, session):
        url = 'https://i.mi.com/find/device/full/status?ts={}'.format(
            int(round(time.time() * 1000)))
        get_device_list_header = {'Cookie': 'userId={};serviceToken={}'.format(
            self.userId, self._Service_Token)}
        try:
            with async_timeout.timeout(15, loop=self.hass.loop):
                r = await session.get(url, headers=get_device_list_header)
            if r.status == 200:
                data = json.loads(await
                    r.text())['data']['devices']

                return data
            else:
                return False
        except BaseException as e:
            _LOGGER.warning(e.args[0])
            return False

    async def _show_config_form(self, user_input):

        data_schema = OrderedDict()
        data_schema[vol.Required(CONF_USERNAME)] = str
        data_schema[vol.Required(CONF_PASSWORD)] = str
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(data_schema), errors=self._errors
        )

    async def async_step_import(self, user_input):
        """Import a config entry.

        Special type of import, we're not actually going to store any data.
        Instead, we're going to rely on the values that are in config file.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title="configuration.yaml", data={})

    async def _check_existing(self, host):
        for entry in self._async_current_entries():
            if host == entry.data.get(CONF_NAME):
                return True

class XiaomiCloudOptionsFlow(config_entries.OptionsFlow):
    """Config flow options for Colorfulclouds."""

    def __init__(self, config_entry):
        """Initialize Colorfulclouds options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(CONF_SCAN_INTERVAL, 5),
                    ):int,
                    vol.Optional(
                        CONF_COORDINATE_TYPE,
                        default=self.config_entry.options.get(CONF_COORDINATE_TYPE, CONF_COORDINATE_TYPE_BAIDU),
                    ): vol.In([CONF_COORDINATE_TYPE_BAIDU, CONF_COORDINATE_TYPE_GOOGLE])
                }
            ),
        )

