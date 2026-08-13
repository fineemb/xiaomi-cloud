"""Todo platform for Xiaomi Cloud notes."""

import copy
import datetime
import json
import logging
import time

import aiohttp
import async_timeout

from homeassistant.components.todo import TodoItem, TodoListEntity
from homeassistant.components.todo.const import (
    TodoItemStatus,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity

from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)

RECORDS_URL = "https://i.mi.com/todo/v1/user/records"
NOTE_URL = "https://i.mi.com/note/note"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up the Xiaomi Cloud to-do list."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    async_add_entities(
        [XiaomiCloudTodoListEntity(hass, coordinator, config_entry)], True
    )


class XiaomiCloudTodoListEntity(TodoListEntity, Entity):
    """To-do list backed by the Xiaomi Cloud notes API."""

    _attr_has_entity_name = True
    _attr_translation_key = "todos"
    _attr_icon = "mdi:clipboard-list-outline"
    _attr_entity_registry_enabled_default = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, hass, coordinator, config_entry) -> None:
        """Set up the to-do list entity."""
        self._hass = hass
        self.coordinator = coordinator
        self._entry_id = config_entry.entry_id
        self._account_name = coordinator._username or "Xiaomi Cloud"
        self._unique_id = f"todo_{config_entry.entry_id}"
        self._attr_todo_items = []
        self._raw_records = {}

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

    @property
    def available(self):
        """Return True if the coordinator is healthy."""
        return self.coordinator.last_update_success

    def _headers(self):
        return {
            "Cookie": self.coordinator.cookie_header(),
            "User-Agent": BROWSER_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN",
            "Referer": "https://i.mi.com/note/h5",
        }

    def _cookie_keys(self):
        """Return the cookie names used in the request header."""
        return [
            part.split("=", 1)[0].strip()
            for part in self.coordinator.cookie_header().split(";")
            if part.strip()
        ]

    async def _fetch_items(self):
        """Fetch all to-do records from the Xiaomi Cloud."""
        session = async_get_clientsession(self.hass)
        try:
            async with async_timeout.timeout(15):
                r = await session.get(
                    RECORDS_URL,
                    headers=self._headers(),
                    params={"ts": int(time.time() * 1000), "limit": 200},
                )
            if r.status != 200:
                self.coordinator.login_result = False
                _LOGGER.warning(
                    "Xiaomi Cloud todo fetch failed with status %s "
                    "(userId set: %s, token=%s..., token length: %s, "
                    "cookie keys: %s)",
                    r.status,
                    bool(self.coordinator.userId),
                    (self.coordinator._Service_Token or "")[:8],
                    len(self.coordinator._Service_Token or ""),
                    self._cookie_keys(),
                )
                return None
            text = await r.text()
            try:
                data = json.loads(text)
            except ValueError as err:
                _LOGGER.warning(
                    "Invalid Xiaomi Cloud todo response: %s (%s)",
                    text[:200],
                    err,
                )
                return None
            if data.get("result") != "ok":
                self.coordinator.login_result = False
                _LOGGER.warning("Xiaomi Cloud todo fetch failed: %s", data)
                return None
            records = data.get("data", {}).get("records", [])
            _LOGGER.debug("Xiaomi Cloud todo records: %s", len(records))
            return self._parse_records(records)
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as err:
            _LOGGER.warning("Failed to fetch Xiaomi Cloud to-do items: %s", err)
            return None

    def _parse_records(self, records):
        """Convert Xiaomi records to Home Assistant TodoItems."""
        items = []
        self._raw_records = {}
        for record in records:
            if record.get("status") == "deleted":
                continue
            entity = (record.get("contentJson") or {}).get("entity") or {}
            uid = str(record.get("id") or entity.get("syncId") or "")
            summary = entity.get("plainText") or entity.get("content") or ""
            if not uid or not summary:
                continue
            finished = entity.get("isFinish") == 1
            due_ms = entity.get("remindTime") or 0
            done_ms = entity.get("markFinishTime") or 0
            self._raw_records[uid] = dict(record)
            items.append(
                TodoItem(
                    uid=uid,
                    summary=str(summary),
                    status=(
                        TodoItemStatus.COMPLETED
                        if finished
                        else TodoItemStatus.NEEDS_ACTION
                    ),
                    due=(
                        datetime.datetime.fromtimestamp(due_ms / 1000)
                        if due_ms
                        else None
                    ),
                    completed=(
                        datetime.datetime.fromtimestamp(done_ms / 1000)
                        if done_ms
                        else None
                    ),
                )
            )
        return items

    async def async_update(self):
        """Refresh the to-do list."""
        items = await self._fetch_items()
        if items is not None:
            self._attr_todo_items = items

    async def async_added_to_hass(self):
        """Fetch the list once at startup."""
        items = await self._fetch_items()
        if items is not None:
            self._attr_todo_items = items
            self.async_write_ha_state()

    async def _post_note(self, url, entry):
        """POST a note entry to the Xiaomi Cloud."""
        session = async_get_clientsession(self.hass)
        data = {
            "entry": json.dumps(entry, ensure_ascii=False),
            "serviceToken": self.coordinator._Service_Token,
        }
        try:
            async with async_timeout.timeout(15):
                r = await session.post(url, headers=self._headers(), data=data)
            text = await r.text()
            if r.status != 200:
                self.coordinator.login_result = False
                _LOGGER.warning(
                    "Xiaomi Cloud note create failed HTTP %s, response headers: %s",
                    r.status,
                    dict(r.headers),
                )
                return False, f"HTTP {r.status}: {text[:120]}"
            try:
                result = json.loads(text)
            except ValueError as err:
                self.coordinator.login_result = False
                return False, f"invalid JSON: {text[:120]}"
            if result.get("result") != "ok":
                self.coordinator.login_result = False
                _LOGGER.warning("Failed to post Xiaomi Cloud note: %s", result)
                return False, str(result)
            return True, None
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Failed to post Xiaomi Cloud note: %s", err)
            return False, str(err)

    async def _post_record(self, url, data):
        """POST a record update to the Xiaomi Cloud."""
        session = async_get_clientsession(self.hass)
        try:
            async with async_timeout.timeout(15):
                r = await session.post(url, headers=self._headers(), data=data)
            if r.status != 200:
                self.coordinator.login_result = False
                return False
            result = await r.json(content_type=None)
            if result.get("result") != "ok":
                self.coordinator.login_result = False
                _LOGGER.warning("Failed to update Xiaomi Cloud record: %s", result)
                return False
            return True
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Failed to update Xiaomi Cloud record: %s", err)
            return False

    async def _post_delete(self, uid, prev_etag):
        """POST a record deletion to the Xiaomi Cloud."""
        session = async_get_clientsession(self.hass)
        data = {
            "prevETag": prev_etag,
            "serviceToken": self.coordinator._Service_Token,
        }
        url = f"{RECORDS_URL}/{uid}/delete"
        try:
            async with async_timeout.timeout(15):
                r = await session.post(url, headers=self._headers(), data=data)
            if r.status != 200:
                self.coordinator.login_result = False
                return False
            result = await r.json(content_type=None)
            if result.get("result") != "ok":
                self.coordinator.login_result = False
                _LOGGER.warning("Failed to delete Xiaomi Cloud record: %s", result)
                return False
            return True
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Failed to delete Xiaomi Cloud record: %s", err)
            return False

    async def _refresh_after_write(self):
        """Reload the list after a successful write."""
        items = await self._fetch_items()
        if items is not None:
            self._attr_todo_items = items
        self.async_write_ha_state()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item to the to-do list."""
        content = (item.summary or "").strip()
        if not content:
            raise HomeAssistantError("A to-do summary is required")

        now_ms = int(time.time() * 1000)
        entry = {
            "content": content,
            "colorId": 0,
            "folderId": "0",
            "createDate": now_ms,
            "modifyDate": now_ms,
        }
        ok, err = await self._post_note(NOTE_URL, entry)
        if not ok:
            # The token may have expired; refresh it once and retry.
            if await self.coordinator._async_refresh_credentials():
                self.coordinator.login_result = True
                ok, err = await self._post_note(NOTE_URL, entry)
            if not ok:
                raise HomeAssistantError(
                    "Failed to create Xiaomi Cloud to-do item: "
                    f"{err or 'unknown error'}"
                )
        await self._refresh_after_write()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update an item in the to-do list."""
        uid = item.uid
        record = self._raw_records.get(uid)
        if record is None:
            await self.async_update()
            record = self._raw_records.get(uid)
        if record is None:
            raise HomeAssistantError(
                f"Unknown Xiaomi Cloud to-do item: {uid}"
            )

        record = copy.deepcopy(record)
        content_json = record.get("contentJson") or {}
        entity = content_json.get("entity") or {}
        now_ms = int(time.time() * 1000)

        # Only replace the content when the summary actually changed,
        # so rich checkbox content is preserved on status toggles.
        content = entity.get("content") or entity.get("plainText") or ""
        if item.summary and item.summary != (entity.get("plainText") or ""):
            content = item.summary
            entity["plainText"] = item.summary
        if not content:
            raise HomeAssistantError(
                "Cannot update a Xiaomi Cloud to-do item with empty content"
            )
        entity["content"] = content

        entity["isFinish"] = (
            1 if item.status == TodoItemStatus.COMPLETED else 0
        )
        entity["markFinishTime"] = (
            now_ms if item.status == TodoItemStatus.COMPLETED else 0
        )
        entity["lastModifiedTime"] = now_ms

        # The update API expects the entity fields flattened into
        # contentJson (no nested "entity" key), unlike the list response.
        record["contentJson"] = {
            **entity,
            "assets": content_json.get("assets", []),
        }

        previous_etag = record.get("eTag") or ""
        data = {
            "previousETag": previous_etag,
            "record": json.dumps(record, ensure_ascii=False),
            "serviceToken": self.coordinator._Service_Token,
        }
        url = f"{RECORDS_URL}/{uid}/update"
        if not await self._post_record(url, data):
            # The token may have expired; refresh it once and retry.
            if await self.coordinator._async_refresh_credentials():
                self.coordinator.login_result = True
                ok = await self._post_record(url, data)
            else:
                ok = False
        if not ok:
            raise HomeAssistantError(
                "Failed to update Xiaomi Cloud to-do item"
            )
        await self._refresh_after_write()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items from the to-do list."""
        failed = []
        for uid in uids:
            record = self._raw_records.get(uid)
            if record is None:
                failed.append(uid)
                continue
            prev_etag = record.get("eTag") or ""
            if not await self._post_delete(uid, prev_etag):
                # The token may have expired; refresh it once and retry.
                if await self.coordinator._async_refresh_credentials():
                    self.coordinator.login_result = True
                    ok = await self._post_delete(uid, prev_etag)
                else:
                    ok = False
                if not ok:
                    failed.append(uid)
        if failed:
            raise HomeAssistantError(
                "Failed to delete Xiaomi Cloud to-do item(s): "
                + ", ".join(failed)
            )
        await self._refresh_after_write()
