"""Shared base entity for sHome."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, OPTIMISTIC_HOLD_SEC
from .coordinator import ShomeCoordinator

_LOGGER = logging.getLogger(__name__)

# 제어 후 실제 반영 확인까지 대기(초)와 재전송 횟수
CONFIRM_DELAY = 4.0
CONFIRM_RETRIES = 2


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

    def _set_pending(self, attr: str, value, ttl: float = OPTIMISTIC_HOLD_SEC) -> None:
        self._pending[attr] = (str(value), time.monotonic() + ttl)

    def _optimistic(self, *pairs) -> None:
        """명령 즉시 UI 반영: (attr, value) 쌍들을 pending으로 걸고 바로 상태 기록.
        API 호출을 기다리지 않으므로 누르는 즉시 스위치가 반응한다."""
        for attr, value in pairs:
            self._set_pending(attr, value)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        # 마지막 폴링 성공 여부에 묶지 않는다: 상태를 아는 기기는 available 유지
        # (제어 직후 빠른 폴링의 일시적 실패로 "사용할 수 없음"이 깜빡이는 것 방지).
        # 이어받기(coordinator) 덕분에 _state는 일시 공백에도 유지된다.
        return bool(self._state)

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

    def _control(self, make_call, pending: list, verify: tuple | None = None) -> None:
        """제어 진입점: 즉시 UI 반영(optimistic) → 명령 전송 → 실제 반영 확인·재전송.

        make_call: 매번 새 coroutine을 반환하는 callable (초기 전송/재전송에 재사용).
        pending: [(attr, value), ...] 즉시 고정할 값들.
        verify: (attr, target) 실제 상태가 target에 도달했는지 확인할 대상 (None이면 확인 안 함).
        """
        self._optimistic(*pending)
        self.hass.async_create_task(self._send_and_confirm(make_call, verify))

    async def _send_and_confirm(self, make_call, verify: tuple | None) -> None:
        try:
            self._apply(await make_call())
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("shome control send failed (%s/%s): %s", self._dtype, self._address, err)
            return
        if verify is None:
            return
        attr, target = verify
        for _ in range(CONFIRM_RETRIES):
            await asyncio.sleep(CONFIRM_DELAY)
            try:
                st = await self.coordinator.api.get_state(self._dtype, self._address)
            except Exception:  # noqa: BLE001
                return
            if not isinstance(st, dict) or st.get(attr) is None:
                return
            if str(st.get(attr)) == str(target):
                self._apply(st)          # 실측이 목표와 일치 → 확정
                return
            # 실제 기기가 목표에 도달 못 함 → 명령 유실로 보고 재전송
            _LOGGER.debug("shome %s/%s %s=%s != %s, resending", self._dtype, self._address,
                          attr, st.get(attr), target)
            self._set_pending(attr, target)
            try:
                self._apply(await make_call())
            except Exception:  # noqa: BLE001
                return
