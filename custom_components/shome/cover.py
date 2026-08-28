"""Cover platform for sHome (커튼 ct)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShomeConfigEntry
from .const import DEV_CURTAIN
from .entity import ShomeDeviceEntity
from .helpers import device_name, inventory_by_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    inv = inventory_by_id(coordinator)
    entities = [
        ShomeCurtain(coordinator, DEV_CURTAIN, addr,
                     device_name(inv, "ct", addr, f"커튼 {addr}"))
        for addr in coordinator.data.get("devices", {}).get(DEV_CURTAIN, {})
    ]
    async_add_entities(entities)


class ShomeCurtain(ShomeDeviceEntity, CoverEntity):
    """커튼 ct — 열림(1)/닫힘(0)/정지(2)."""

    _attr_name = None
    _attr_device_class = CoverDeviceClass.CURTAIN
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    @property
    def is_closed(self) -> bool | None:
        p = self._get("power")
        return None if p is None else str(p) == "0"

    async def async_open_cover(self, **kwargs: Any) -> None:
        r = await self.coordinator.api.set_power(self._dtype, self._address, "1"); self._set_pending("power", "1"); self._apply(r)

    async def async_close_cover(self, **kwargs: Any) -> None:
        r = await self.coordinator.api.set_power(self._dtype, self._address, "0"); self._set_pending("power", "0"); self._apply(r)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        r = await self.coordinator.api.set_power(self._dtype, self._address, "2"); self._set_pending("power", "2"); self._apply(r)
