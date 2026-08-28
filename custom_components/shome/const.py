"""Constants for the sHome (Samsung SDS / Zigbang IHP) integration."""
from __future__ import annotations

DOMAIN = "shome"

# --- Cloud endpoint / protocol -------------------------------------------
DEFAULT_BASE_URL = "https://shome-api.samsung-ihp.com/"
SALT = "IHRESTAPI"
APP_VERSION = "3.1.48"
OS_TYPE = "ANDROID"
DEFAULT_LANGUAGE = "KOR"

# --- Config entry keys ----------------------------------------------------
CONF_USER_ID = "user_id"
CONF_PASSWORD = "password"
CONF_BASE_URL = "base_url"
CONF_DEVICE_ID = "device_id"          # mobileDeviceIdno (stable per install)
CONF_LANGUAGE = "language"

DEFAULT_SCAN_INTERVAL = 30            # seconds
CONF_SCAN_INTERVAL = "scan_interval"
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 600

# --- Device type path segments (v18 MHPS) --------------------------------
DEV_LIGHT = "light"
DEV_DIMMING = "dimming"
DEV_SENSITIVE_LIGHT = "sensitive_light"
DEV_ALL_LIGHT = "all_light"
DEV_AIRCON = "aircon"
DEV_BOILER_BL = "boiler/bl"
DEV_BOILER_BR = "boiler/br"
DEV_FAN = "fan"
DEV_CURTAIN = "curtain"
DEV_GASVALVE = "gasvalve"
DEV_OUTSWITCH = "outswitch"

# device types that expose an all_state monitoring endpoint
ALL_STATE_TYPES = [
    DEV_LIGHT,
    DEV_DIMMING,
    DEV_SENSITIVE_LIGHT,
    DEV_ALL_LIGHT,
    DEV_AIRCON,
    DEV_BOILER_BL,
    DEV_BOILER_BR,
    DEV_FAN,
    DEV_CURTAIN,
    DEV_GASVALVE,
    DEV_OUTSWITCH,
]

# device-type numeric constants (from shnDevice.java)
DEVICE_JM = 1001  # 조명 light
DEVICE_BL = 1002  # 난방 boiler
DEVICE_AC = 1003  # 냉방 aircon
DEVICE_GV = 1004  # 가스밸브 gas valve
DEVICE_VF = 1005  # 환기 fan
DEVICE_CT = 1006  # 커튼 curtain
DEVICE_OS = 1007  # 퇴실 outswitch

# --- Energy types (contents/norems/energy) -------------------------------
ENERGY_TYPES = ["electric", "water", "gas", "heating", "hotwater"]
