'''
Author        : fineemb
Github        : https://github.com/fineemb
Description   : 
Date          : 2020-09-12 20:46:33
LastEditors   : fineemb
LastEditTime  : 2020-09-13 14:49:50
'''


"""Const file for Xiaomi Cloud."""
CONF_WAKE_ON_START = "enable_wake_on_start"
DOMAIN = "xiaomi_cloud"
COORDINATOR = "coordinator"
DATA_LISTENER = "listener"
UNDO_UPDATE_LISTENER = "undo_update_listener"
DEFAULT_SCAN_INTERVAL = 660
DEFAULT_WAKE_ON_START = False
MIN_SCAN_INTERVAL = 60
SIGNAL_STATE_UPDATED = f"{DOMAIN}.updated"
TESLA_COMPONENTS = [
    "sensor",
    "lock",
    "climate",
    "binary_sensor",
    "device_tracker",
    "switch",
]
ICONS = {
    "battery sensor": "mdi:battery",
    "range sensor": "mdi:gauge",
    "mileage sensor": "mdi:counter",
    "parking brake sensor": "mdi:car-brake-parking",
    "charger sensor": "mdi:ev-station",
    "charger switch": "mdi:battery-charging",
    "update switch": "mdi:update",
    "maxrange switch": "mdi:gauge-full",
    "temperature sensor": "mdi:thermometer",
    "location tracker": "mdi:crosshairs-gps",
    "charging rate sensor": "mdi:speedometer",
    "sentry mode switch": "mdi:shield-car",
}