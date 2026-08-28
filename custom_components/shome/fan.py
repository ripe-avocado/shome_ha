"""Fan platform for sHome (환기 vf)."""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from . import ShomeConfigEntry
from .const import DEV_FAN
from .entity import ShomeDeviceEntity
from .helpers import device_name, inventory_by_id

# flowRate: 1=3단(강), 2=2단(중), 3=1단(약)  -> low..high order
FAN_SPEEDS = ["3", "2", "1"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    inv = inventory_by_id(coordinator)
    entities = [
        ShomeFan(coordinator, DEV_FAN, addr, device_name(inv, "vf", addr, f"환기 {addr}"))
        for addr in coordinator.data.get("devices", {}).get(DEV_FAN, {})
    ]
    async_add_entities(entities)


class ShomeFan(ShomeDeviceEntity, FanEntity):
    """환기 vf — on/off + 풍량(flowRate)."""

    _attr_name = None
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = len(FAN_SPEEDS)

    @property
    def is_on(self) -> bool | None:
        p = self._get("power")
        return None if p is None else str(p) == "1"

    @property
    def percentage(self) -> int | None:
        fr = self._get("flowRate")
        if fr in (None, "", "0"):
            return 0
        if str(fr) not in FAN_SPEEDS:
            return None
        return ordered_list_item_to_percentage(FAN_SPEEDS, str(fr))

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        value = percentage_to_ordered_list_item(FAN_SPEEDS, percentage)
        res = await self.coordinator.api.set_one_function(self._dtype, self._address, "flowrate", value)
        self._set_pending("flowRate", value)
        self._apply(res)

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any
    ) -> None:
        res = await self.coordinator.api.set_power(self._dtype, self._address, "1")
        self._set_pending("power", "1")
        self._apply(res)
        if percentage:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        res = await self.coordinator.api.set_power(self._dtype, self._address, "0")
        self._set_pending("power", "0")
        self._apply(res)
