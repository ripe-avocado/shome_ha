"""Light platform for sHome (조명 jm, 디밍 dm, 감성조명 sjm, 일괄조명 alo)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShomeConfigEntry
from .const import DEV_ALL_LIGHT, DEV_DIMMING, DEV_LIGHT, DEV_SENSITIVE_LIGHT
from .coordinator import ShomeCoordinator
from .entity import ShomeDeviceEntity
from .helpers import device_name, inventory_by_id

# type prefix (in inventory id / state.type) per dtype path
_PREFIX = {DEV_LIGHT: "jm", DEV_DIMMING: "dm", DEV_SENSITIVE_LIGHT: "sjm", DEV_ALL_LIGHT: "alo"}
DIM_MAX = 7  # dimming levels 1..7 (dm_basic.dat)
# 감성조명 sjm modes (sjm_basic.dat): 꺼짐=0, 일상=1, 독서=2, 영화=3, 다과=4
SJM_MODES = {"1": "일상", "2": "독서", "3": "영화", "4": "다과"}
SJM_MODES_REV = {v: k for k, v in SJM_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    inv = inventory_by_id(coordinator)
    entities: list[LightEntity] = []
    for dtype in (DEV_LIGHT, DEV_ALL_LIGHT):
        for addr in coordinator.data.get("devices", {}).get(dtype, {}):
            name = device_name(inv, _PREFIX[dtype], addr, f"조명 {addr}")
            entities.append(ShomeOnOffLight(coordinator, dtype, addr, name))
    for addr in coordinator.data.get("devices", {}).get(DEV_DIMMING, {}):
        name = device_name(inv, "dm", addr, f"디밍 {addr}")
        entities.append(ShomeDimmingLight(coordinator, DEV_DIMMING, addr, name))
    for addr in coordinator.data.get("devices", {}).get(DEV_SENSITIVE_LIGHT, {}):
        name = device_name(inv, "sjm", addr, f"감성조명 {addr}")
        entities.append(ShomeSensitiveLight(coordinator, DEV_SENSITIVE_LIGHT, addr, name))
    async_add_entities(entities)


class ShomeOnOffLight(ShomeDeviceEntity, LightEntity):
    """조명 jm / 일괄조명 alo — on/off only."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_name = None

    @property
    def is_on(self) -> bool | None:
        p = self._get("power")
        return None if p is None else str(p) == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._optimistic(("power", "1"))
        res = await self.coordinator.api.set_power(self._dtype, self._address, "1")
        self._apply(res)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._optimistic(("power", "0"))
        res = await self.coordinator.api.set_power(self._dtype, self._address, "0")
        self._apply(res)


class ShomeDimmingLight(ShomeDeviceEntity, LightEntity):
    """디밍 dm — on/off + brightness (level 1..7)."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_name = None

    @property
    def is_on(self) -> bool | None:
        p = self._get("power")
        lvl = self._get("level")
        if p is not None:
            return str(p) == "1"
        return bool(lvl and int(lvl) > 0)

    @property
    def brightness(self) -> int | None:
        lvl = self._get("level")
        if lvl in (None, ""):
            return None
        return round(int(lvl) / DIM_MAX * 255)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            level = max(1, round(kwargs[ATTR_BRIGHTNESS] / 255 * DIM_MAX))
            self._optimistic(("level", level), ("power", "1"))
            res = await self.coordinator.api.set_function(self._dtype, self._address, str(level))
        else:
            self._optimistic(("power", "1"))
            res = await self.coordinator.api.set_power(self._dtype, self._address, "1")
        self._apply(res)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._optimistic(("power", "0"))
        res = await self.coordinator.api.set_power(self._dtype, self._address, "0")
        self._apply(res)


class ShomeSensitiveLight(ShomeDeviceEntity, LightEntity):
    """감성조명 sjm — on/off + 모드(일상/독서/영화/다과) via effect. (커버 없이 미검증 — 커뮤니티 테스트)."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(SJM_MODES.values())
    _attr_name = None

    @property
    def is_on(self) -> bool | None:
        p = self._get("power")
        if p is not None:
            return str(p) == "1"
        mode = self._get("mode")
        return None if mode is None else str(mode) != "0"

    @property
    def effect(self) -> str | None:
        return SJM_MODES.get(str(self._get("mode")))

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] in SJM_MODES_REV:
            mode = SJM_MODES_REV[kwargs[ATTR_EFFECT]]
            self._optimistic(("mode", mode))
            res = await self.coordinator.api.set_function(self._dtype, self._address, mode)
        else:
            self._optimistic(("power", "1"))
            res = await self.coordinator.api.set_power(self._dtype, self._address, "1")
        self._apply(res)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._optimistic(("power", "0"), ("mode", "0"))
        res = await self.coordinator.api.set_power(self._dtype, self._address, "0")
        self._apply(res)
