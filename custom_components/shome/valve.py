"""Valve platform for sHome (가스밸브 gv) — 안전상 닫기 전용."""
from __future__ import annotations

from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShomeConfigEntry
from .const import DEV_GASVALVE
from .entity import ShomeDeviceEntity
from .helpers import device_name, inventory_by_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    inv = inventory_by_id(coordinator)
    entities = [
        ShomeGasValve(coordinator, DEV_GASVALVE, addr,
                      device_name(inv, "gv", addr, f"가스밸브 {addr}"))
        for addr in coordinator.data.get("devices", {}).get(DEV_GASVALVE, {})
    ]
    async_add_entities(entities)


class ShomeGasValve(ShomeDeviceEntity, ValveEntity):
    """가스밸브 gv — 원격 열기는 안전상 불가, 닫기만 지원 (power 열림=1/잠금=0)."""

    _attr_name = None
    _attr_device_class = ValveDeviceClass.GAS
    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.CLOSE

    @property
    def is_closed(self) -> bool | None:
        p = self._get("power")
        return None if p in (None, "") else str(p) == "0"

    async def async_close_valve(self, **kwargs: Any) -> None:
        self._control(lambda: self.coordinator.api.set_power(self._dtype, self._address, "0"), [("power", "0")], verify=("power", "0"))
