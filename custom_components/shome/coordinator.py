"""DataUpdateCoordinator for sHome."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ShomeApi, ShomeAuthError, ShomeConnectionError
from .const import (
    ALL_STATE_TYPES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    FAST_SCAN_CYCLES,
    FAST_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class ShomeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the sHome cloud and holds normalized device/energy state.

    data structure:
        {
          "devices": { <dtype>: { <address>: <Monitoring dict> } },
          "inventory": [ {id,name,state,model,location} ],
          "home_mode": {"state": str, "modeList": [...] },
          "energy": <energy recently dict>,
          "expense": <expense dict>,
        }
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ShomeApi) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        # 저장된 값이 범위를 벗어나도 안전하게 클램프 (서버 과부하 방지)
        interval = max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, int(interval)))
        self._normal_interval = interval
        self._fast_remaining = 0
        super().__init__(
            hass,
            _LOGGER,
            name="shome",
            update_interval=timedelta(seconds=interval),
        )
        self.entry = entry
        self.api = api
        # which device types actually returned data (discovered on first poll)
        self.present_types: list[str] = []
        self._poll_count = 0
        self._energy_ts = 0.0
        self._energy_cache = None
        self._visit_ts = 0.0
        self._visit_cache = None
        self._visit_interval = 120.0  # 방문 이력은 2분마다
        self._expense_cache = None
        # 에너지/관리비는 월 단위 데이터 → 30분마다만 갱신
        self._energy_interval = 1800.0
        # 새 기기 감지를 위해 20회마다 전체 타입 재스캔
        self._full_rescan_every = 20

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self.api.async_ensure_token()
            # 이전 폴링의 기기 상태를 이어받아, 이번 사이클에 일시적으로 못 읽은 기기가
            # "사용할 수 없음"으로 사라지지 않게 한다(제어 직후 전환 중 공백 방지).
            prev = self.data or {}
            data: dict[str, Any] = {
                "devices": {k: dict(v) for k, v in (prev.get("devices") or {}).items()},
                "inventory": prev.get("inventory") or [],
                "home_mode": prev.get("home_mode") or {},
                "energy": None, "expense": None,
                "legacy": prev.get("legacy") or [],
                "visit": prev.get("visit"),
            }

            # --- LEGACY (구형 세대): MHPS가 아니면 통합 기기목록으로 열거 (실험적) ---
            if not self.api.is_mhps:
                try:
                    res = await self.api.get_legacy_devices()
                    data["legacy"] = res.get("deviceList", []) if isinstance(res, dict) else []
                except (ShomeConnectionError, Exception) as err:  # noqa: BLE001
                    _LOGGER.debug("legacy device list failed: %s", err)
                # 홈모드/에너지는 legacy에서도 시도
                try:
                    data["home_mode"] = await self.api.get_home_mode()
                except ShomeConnectionError:
                    pass
                self.present_types = []
                return data

            # device inventory (best-effort) — 실패 시 이전 값 유지
            try:
                inv = await self.api.get_all_list()
                inv_list = inv.get("deviceList") if isinstance(inv, dict) else None
                if inv_list:
                    data["inventory"] = inv_list
            except ShomeConnectionError as err:
                _LOGGER.debug("all_list failed: %s", err)

            # per-type monitoring — 첫 폴링/주기적 재스캔은 전체, 평소엔 존재하는 타입만 조회해 요청 절감
            self._poll_count += 1
            full_scan = (not self.present_types) or (self._poll_count % self._full_rescan_every == 0)
            scan_types = ALL_STATE_TYPES if full_scan else self.present_types
            for dtype in scan_types:
                try:
                    res = await self.api.get_all_state(dtype)
                except ShomeConnectionError as err:
                    _LOGGER.debug("all_state %s failed: %s", dtype, err)
                    continue
                if not isinstance(res, dict):
                    continue
                dev_list = res.get("deviceList") or []
                if not dev_list:
                    continue
                bucket: dict[str, Any] = {}
                for mon in dev_list:
                    addr = str(mon.get("address"))
                    bucket[addr] = mon
                data["devices"][dtype] = bucket

            if full_scan:
                self.present_types = list(data["devices"].keys())

            # home mode — 실패 시 이전 값 유지
            try:
                hm = await self.api.get_home_mode()
                if isinstance(hm, dict) and hm.get("modeList"):
                    data["home_mode"] = hm
            except ShomeConnectionError:
                pass

            # energy / expense — 월 단위 데이터라 30분마다만 실제 조회, 그 외엔 캐시 사용
            now = time.monotonic()
            if self._energy_cache is None or (now - self._energy_ts) >= self._energy_interval:
                try:
                    self._energy_cache = await self.api.get_energy_towmond()
                except ShomeConnectionError:
                    pass
                try:
                    self._expense_cache = await self.api.get_expense()
                except ShomeConnectionError:
                    pass
                self._energy_ts = now
            data["energy"] = self._energy_cache
            data["expense"] = self._expense_cache

            # 방문 이력 — 2분마다 조회 (이벤트성이지만 과도한 폴링 방지)
            if self._visit_cache is None or (now - self._visit_ts) >= self._visit_interval:
                try:
                    self._visit_cache = await self.api.get_visit_all()
                    self._visit_ts = now
                except ShomeConnectionError:
                    pass
            data["visit"] = self._visit_cache

            # 적응형 폴링: 제어 직후 몇 회는 빠르게, 이후 평상 주기로 복귀
            if self._fast_remaining > 0:
                self._fast_remaining -= 1
                self.update_interval = timedelta(seconds=FAST_SCAN_INTERVAL)
            else:
                self.update_interval = timedelta(seconds=self._normal_interval)

            return data

        except ShomeAuthError as err:
            # token expired -> drop token so next cycle re-logs in.
            # On lockout (result==2/1) back off instead of hammering.
            if getattr(err, "lock_minutes", None):
                self.update_interval = timedelta(minutes=int(err.lock_minutes) + 1)
                _LOGGER.warning("sHome 계정 잠금: %s (백오프)", err)
            else:
                self.api._token = None  # noqa: SLF001
            raise UpdateFailed(str(err)) from err
        except ShomeConnectionError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def activate_fast_poll(self, cycles: int = FAST_SCAN_CYCLES) -> None:
        """제어 직후 호출 — 잠깐 빠른 주기로 재조회해 외부/연쇄 변화를 빨리 반영."""
        self._fast_remaining = max(self._fast_remaining, cycles)
        self.update_interval = timedelta(seconds=FAST_SCAN_INTERVAL)
        self.hass.async_create_task(self.async_request_refresh())
