"""Shared base entity for sHome."""
from __future__ import annotations

import time
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
        # 제어 후 명령값을 확정/만료 전까지 고정 (폴링의 전환중 stale 값이 덮어쓰지 않게)
        self._pending: dict[str, tuple[str, float]] = {}
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

    def _get(self, attr: str):
        """폴링값 대신, 제어 직후 고정된 명령값을 우선 반환 (확정/만료 시 해제)."""
        poll_val = self._state.get(attr)
        pend = self._pending.get(attr)
        if pend is None:
            return poll_val
        value, expiry = pend
        if poll_val is not None and str(poll_val) == str(value):
            del self._pending[attr]      # 폴링이 명령값과 일치 → 확정
            return poll_val
        if time.monotonic() < expiry:
            return value                 # 아직 고정 구간 → 명령값 유지
        del self._pending[attr]          # 만료 → 실제 폴링값 신뢰
        return poll_val

    def _set_pending(self, attr: str, value, ttl: float = 12.0) -> None:
        self._pending[attr] = (str(value), time.monotonic() + ttl)

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
        # 제어 직후 잠깐 빠른 폴링으로 연쇄/외부 변화 반영
        self.coordinator.activate_fast_poll()
