"""Shared base entity for sHome."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ShomeCoordinator


class ShomeDeviceEntity(CoordinatorEntity[ShomeCoordinator]):
    """Base for a controllable device addressed by (dtype, address)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ShomeCoordinator, dtype: str, address: str,
                 name: str | None = None) -> None:
        super().__init__(coordinator)
        self._dtype = dtype
        self._address = str(address)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{dtype.replace('/', '_')}_{address}"
        self._base_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=name or f"{dtype} {address}",
            manufacturer="Samsung SDS / Zigbang",
            model=dtype,
            via_device=(DOMAIN, coordinator.entry.entry_id),
        )

    @property
    def _state(self) -> dict[str, Any]:
        """Latest Monitoring dict for this device (or empty)."""
        return (
            self.coordinator.data.get("devices", {})
            .get(self._dtype, {})
            .get(self._address, {})
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self._state)

    def _apply(self, monitoring: dict[str, Any] | None) -> None:
        """Merge a control-response Monitoring into coordinator cache for snappy UI."""
        if not isinstance(monitoring, dict):
            return
        bucket = self.coordinator.data.setdefault("devices", {}).setdefault(self._dtype, {})
        addr = str(monitoring.get("address", self._address))
        cur = bucket.get(addr, {})
        cur.update({k: v for k, v in monitoring.items() if v is not None})
        bucket[addr] = cur
        self.async_write_ha_state()
