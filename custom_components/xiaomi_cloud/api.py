"""Xiaomi Cloud Find Device v3 response helpers."""

import hashlib
import json
import math
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

COORDINATE_TYPE_MAP = {
    "baidu": "baidu",
    "google": "google",
    "original": "google",
}

PI = math.pi
EARTH_SEMIMAJOR_AXIS = 6378245.0
EARTH_ECCENTRICITY_SQUARED = 0.00669342162296594323
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def _outside_china(longitude: float, latitude: float) -> bool:
    return not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271)


def _transform_latitude(x: float, y: float) -> float:
    result = -100 + 2 * x + 3 * y + 0.2 * y**2 + 0.1 * x * y
    result += 0.2 * math.sqrt(abs(x))
    result += (20 * math.sin(6 * x * PI) + 20 * math.sin(2 * x * PI)) * 2 / 3
    result += (20 * math.sin(y * PI) + 40 * math.sin(y / 3 * PI)) * 2 / 3
    result += (160 * math.sin(y / 12 * PI) + 320 * math.sin(y * PI / 30)) * 2 / 3
    return result


def _transform_longitude(x: float, y: float) -> float:
    result = 300 + x + 2 * y + 0.1 * x**2 + 0.1 * x * y
    result += 0.1 * math.sqrt(abs(x))
    result += (20 * math.sin(6 * x * PI) + 20 * math.sin(2 * x * PI)) * 2 / 3
    result += (20 * math.sin(x * PI) + 40 * math.sin(x / 3 * PI)) * 2 / 3
    result += (150 * math.sin(x / 12 * PI) + 300 * math.sin(x / 30 * PI)) * 2 / 3
    return result


def gcj02_to_wgs84(longitude: float, latitude: float) -> tuple[float, float]:
    """Convert GCJ-02 coordinates to WGS-84."""
    if _outside_china(longitude, latitude):
        return longitude, latitude

    delta_latitude = _transform_latitude(longitude - 105, latitude - 35)
    delta_longitude = _transform_longitude(longitude - 105, latitude - 35)
    latitude_radians = latitude / 180 * PI
    magic = math.sin(latitude_radians)
    magic = 1 - EARTH_ECCENTRICITY_SQUARED * magic**2
    square_root_magic = math.sqrt(magic)
    delta_latitude = delta_latitude * 180 / (
        (EARTH_SEMIMAJOR_AXIS * (1 - EARTH_ECCENTRICITY_SQUARED))
        / (magic * square_root_magic)
        * PI
    )
    delta_longitude = delta_longitude * 180 / (
        EARTH_SEMIMAJOR_AXIS
        / square_root_magic
        * math.cos(latitude_radians)
        * PI
    )
    return longitude - delta_longitude, latitude - delta_latitude


def device_status_params(
    device: dict[str, Any], sync_mode: int, timestamp: int
) -> dict[str, Any]:
    """Build query parameters for a Find Device v3 status request."""
    return {
        "ts": timestamp,
        "targetUserId": device["userId"],
        "targetFid": device["fid"],
        "syncMode": sync_mode,
    }


def noise_command_params(
    device: dict[str, Any], identifier: str
) -> dict[str, Any] | None:
    """Build the current Find Device play-sound command for a component."""
    component = next(
        (
            item
            for item in device.get("componentList", [])
            if item.get("did") == identifier or device.get("fid") == identifier
        ),
        None,
    )
    if component is None or 6 not in component.get("supportCmds", []):
        return None
    return {
        "targetUserId": device["userId"],
        "targetFid": device["fid"],
        "targetComponentId": component["componentId"],
        "commandType": 6,
    }


def lost_command_params(
    device: dict[str, Any],
    identifier: str,
    *,
    phone: str,
    content: str,
    notify: bool,
) -> dict[str, Any] | None:
    """Build the current Find Device lost-mode command for a component."""
    component = next(
        (
            item
            for item in device.get("componentList", [])
            if item.get("did") == identifier or device.get("fid") == identifier
        ),
        None,
    )
    if component is None or 32 not in component.get("supportCmds", []):
        return None
    return {
        "targetUserId": device["userId"],
        "targetFid": device["fid"],
        "targetComponentId": component["componentId"],
        "commandType": 32,
        "lostPhone": phone,
        "lostContent": content,
        "foundNotify": "enable" if notify else "disable",
    }


def browser_login_data(
    password_url: str, username: str, password: str
) -> dict[str, str]:
    """Build password auth data from Xiaomi's dynamic browser context."""
    query = parse_qs(urlparse(password_url).query, keep_blank_values=True)
    return {
        "bizDeviceType": query.get("bizDeviceType", [""])[0],
        "needTheme": query.get("needTheme", ["false"])[0],
        "theme": query.get("theme", [""])[0],
        "showActiveX": query.get("showActiveX", ["false"])[0],
        "serviceParam": query["serviceParam"][0],
        "callback": query["callback"][0],
        "qs": query["qs"][0],
        "sid": query.get("sid", ["i.mi.com"])[0],
        "_sign": query["_sign"][0],
        "user": username,
        "hash": hashlib.md5(password.encode()).hexdigest().upper(),
        "_json": "true",
    }


def verification_context(notification_url: str) -> str:
    """Extract the signed identity context from a notification URL."""
    return parse_qs(urlparse(notification_url).query)["context"][0]


def config_entry_data(
    username: str,
    password: str,
    service_token: str,
    user_id: str,
    cookie_header: str = "",
) -> dict[str, str]:
    """Build config entry data after successful browser authorization."""
    return {
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
        "serviceToken": service_token,
        "userId": user_id,
        "cookies": cookie_header,
    }


def browser_cookie_header(
    cookie_header: str,
    service_token: str | None,
    user_id: str | None,
    csrf_token: str,
) -> str:
    """Normalize a cookie header into a browser-like i.mi.com session."""
    base = cookie_header or ""
    if not base and service_token and user_id:
        base = f"userId={user_id};serviceToken={service_token}"

    cookies = {}
    for part in base.split(";"):
        if "=" in part:
            key, _, value = part.strip().partition("=")
            cookies[key] = value

    if user_id and "userId" not in cookies:
        cookies["userId"] = user_id
    if service_token and "serviceToken" not in cookies:
        cookies["serviceToken"] = service_token

    # Browser sessions normally carry these extra cookies; the note/todo
    # API appears to expect them.
    cookies.setdefault("uLocale", "zh_CN")
    cookies.setdefault("iplocale", "zh_CN")
    cookies.setdefault("i.mi.com_isvalid_servicetoken", "true")
    cookies.setdefault("i.mi.com_istrudev", "true")
    cookies.setdefault("csrfToken", csrf_token)

    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    """Parse a Cookie header into a key/value map."""
    cookies = {}
    for part in (cookie_header or "").split(";"):
        if "=" in part:
            key, _, value = part.strip().partition("=")
            cookies[key.strip()] = value.strip()
    return cookies


async def browser_find_device_credentials(
    session: aiohttp.ClientSession, username: str, password: str
) -> tuple[str, str, str] | None:
    """Authenticate in Xiaomi's browser context and return Find Device cookies."""
    try:
        headers = {"User-Agent": BROWSER_USER_AGENT}
        async with session.get(
            "https://i.mi.com/api/user/login",
            params={
                "ts": int(time.time() * 1000),
                "followUp": "https://i.mi.com/",
                "_locale": "zh_CN",
            },
            headers=headers,
        ) as response:
            if response.status != 200:
                return None
            login_info = await response.json(content_type=None)

        login_url = (login_info.get("data") or {}).get("loginUrl")
        if not login_url:
            return None

        async with session.get(login_url, headers=headers) as response:
            await response.read()
            password_url = str(response.url)

        async with session.post(
            "https://account.xiaomi.com/pass/serviceLoginAuth2",
            headers={
                **headers,
                "Origin": "https://account.xiaomi.com",
                "Referer": password_url,
                "Accept": "application/json, text/plain, */*",
            },
            data=browser_login_data(password_url, username, password),
        ) as response:
            if response.status != 200:
                return None
            text = await response.text()
        auth = json.loads(text.removeprefix("&&&START&&&"))
        if auth.get("code") != 0:
            return None

        notification_url = auth.get("notificationUrl")
        if not notification_url:
            return None
        async with session.get(notification_url, headers=headers) as response:
            if response.status != 200:
                return None
            await response.read()

        async with session.get(
            "https://account.xiaomi.com/identity/list",
            params={
                "sid": "i.mi.com",
                "supportedMask": "0",
                "_locale": "zh_CN",
                "context": verification_context(notification_url),
            },
            headers={
                **headers,
                "Referer": notification_url,
                "Accept": "application/json, text/plain, */*",
            },
        ) as response:
            if response.status != 200:
                return None
            text = await response.text()
        identity = json.loads(text.removeprefix("&&&START&&&"))
        find_device_url = identity.get("findDeviceUrl")
        if not find_device_url:
            return None

        async with session.get(
            find_device_url, headers=headers, allow_redirects=True
        ) as response:
            if response.status != 200:
                return None
            await response.read()

        # Visit the note page so the server sets any note-related cookies.
        async with session.get("https://i.mi.com/note/h5", headers=headers) as response:
            await response.read()

        cookies = {cookie.key: cookie.value for cookie in session.cookie_jar}
        service_token = cookies.get("serviceToken")
        user_id = cookies.get("userId")
        if not service_token or not user_id:
            return None

        # Collect every cookie that is valid for the i.mi.com domain so that
        # the note/todo APIs receive the same session as a browser would.
        parts = []
        for cookie in session.cookie_jar:
            domain = cookie.get("domain")
            if domain and not (
                domain.endswith("i.mi.com") or domain.endswith(".mi.com")
            ):
                continue
            parts.append(f"{cookie.key}={cookie.value}")
        cookie_header = "; ".join(parts)
        # Make sure the two essential cookies are always present.
        if user_id and "userId=" not in cookie_header:
            cookie_header = f"userId={user_id}; " + cookie_header
        if service_token and "serviceToken=" not in cookie_header:
            cookie_header += f"; serviceToken={service_token}"
        return service_token, user_id, cookie_header
    except (aiohttp.ClientError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def check_todo_access(
    session: aiohttp.ClientSession, cookie_header: str
) -> bool:
    """Check whether the cookie header can access the to-do API."""
    try:
        async with session.get(
            "https://i.mi.com/todo/v1/user/records",
            params={"ts": int(time.time() * 1000), "limit": 1},
            headers={
                "Cookie": cookie_header,
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN",
                "Referer": "https://i.mi.com/note/h5",
            },
        ) as response:
            if response.status != 200:
                return False
            data = await response.json(content_type=None)
            return data.get("result") == "ok"
    except (aiohttp.ClientError, ValueError, KeyError):
        return False


async def check_find_access(
    session: aiohttp.ClientSession, user_id: str, service_token: str
) -> bool:
    """Check whether the credentials can access the Find Device API."""
    try:
        async with session.get(
            "https://i.mi.com/find/v3/device/status/list",
            params={"ts": int(time.time() * 1000)},
            headers={
                "Cookie": f"userId={user_id};serviceToken={service_token}",
                "Accept-Language": "zh-CN",
                "Referer": "https://i.mi.com/find",
            },
        ) as response:
            if response.status != 200:
                return False
            data = await response.json(content_type=None)
            return data.get("result") == "ok"
    except (aiohttp.ClientError, ValueError, KeyError):
        return False


def model_name(device: dict[str, Any]) -> str:
    """Return the localized model name from a v3 device record."""
    component_models = device.get("componentModelInfo", {})
    model_info = next(iter(component_models.values()), {})
    names = model_info.get("modelName", {})
    value = names.get("zhCN") or names.get("defaultName")
    if value:
        try:
            return json.loads(value)["modelName"]
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    return device.get("deviceType", "Xiaomi device")


def component(device: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first component that supports location."""
    components = device.get("componentList", [])
    return next(
        (item for item in components if item.get("locationList")),
        components[0] if components else None,
    )


def normalize_device(device: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a v3 device record to the integration entity data contract."""
    device_component = component(device)
    if not device_component:
        return None

    locations = device_component.get("locationList", [])
    if not locations:
        return None

    location = locations[0]
    transformed = location.get("gpsInfoTransformed", [])
    if not transformed:
        return None

    return {
        "fid": device["fid"],
        "target_user_id": device["userId"],
        "imei": device_component.get("did", device["fid"]),
        "model": model_name(device),
        "version": "",
        "status": device.get("status"),
        "locations": transformed,
        "power": device_component.get("batteryInfo", {}).get("level", 0),
        "phone": 0,
        "updated_at": location.get("clientUpdateTime", 0),
        "is_locating": device.get("isLocating", False),
    }


def entity_data(
    device: dict[str, Any], coordinate_type: str
) -> dict[str, Any] | None:
    """Convert normalized v3 data into the tracker entity contract."""
    normalized = normalize_device(device)
    if not normalized:
        return None

    requested_type = COORDINATE_TYPE_MAP.get(coordinate_type, coordinate_type)
    location = next(
        (
            item
            for item in normalized["locations"]
            if item.get("coordinateType") == requested_type
        ),
        normalized["locations"][0],
    )

    latitude = location["latitude"]
    longitude = location["longitude"]
    reported_type = location.get("coordinateType", requested_type)
    if coordinate_type == "original":
        longitude, latitude = gcj02_to_wgs84(longitude, latitude)
        reported_type = "wgs84"

    device_component = component(device)
    battery_info = (
        device_component.get("batteryInfo", {}) if device_component else {}
    )
    lost_mode_info = device.get("lostModeInfo", {}) or {}
    offline_find_info = device.get("offlineFindInfo", {}) or {}
    wipe_info = device.get("wipeInfo", {}) or {}

    return {
        "device_lat": latitude,
        "device_accuracy": int(location.get("accuracy", 0)),
        "device_lon": longitude,
        "coordinate_type": reported_type,
        "device_power": normalized["power"],
        "device_phone": normalized["phone"],
        "address": location.get("address", ""),
        "address_component": location.get("addressComponent", ""),
        "source_type": location.get("sourceType", ""),
        "charging": battery_info.get("charging", False),
        "device_location_update_time": time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(normalized["updated_at"] / 1000),
        ),
        "imei": normalized["imei"],
        "fid": normalized["fid"],
        "target_user_id": normalized["target_user_id"],
        "model": normalized["model"],
        "version": normalized["version"],
        "status": normalized["status"],
        "lost_mode": lost_mode_info.get("status", "disable"),
        "offline_find": offline_find_info.get("status", "disable"),
        "wipe": wipe_info.get("status", "disable"),
        "share_location": device.get("shareLocation", False),
        "support_sms": device.get("supportSms", False),
    }
