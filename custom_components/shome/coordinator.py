"""DataUpdateCoordinator for sHome."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ShomeApi, ShomeAuthError, ShomeConnectionError
from .const import ALL_STATE_TYPES, DEFAULT_SCAN_INTERVAL

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
        super().__init__(
            hass,
            _LOGGER,
            name="shome",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self.api = api
        # which device types actually returned data (discovered on first poll)
        self.present_types: list[str] = []

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self.api.async_ensure_token()
            data: dict[str, Any] = {"devices": {}, "inventory": [], "home_mode": {},
                                    "energy": None, "expense": None, "legacy": []}

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

            # device inventory (best-effort)
            try:
                inv = await self.api.get_all_list()
                data["inventory"] = inv.get("deviceList", []) if isinstance(inv, dict) else []
            except ShomeConnectionError as err:
                _LOGGER.debug("all_list failed: %s", err)

            # per-type monitoring
            for dtype in ALL_STATE_TYPES:
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

            self.present_types = list(data["devices"].keys())

            # home mode
            try:
                data["home_mode"] = await self.api.get_home_mode()
            except ShomeConnectionError:
                pass

            # energy / expense (best-effort; may not exist for every complex)
            # towmond returns all energy types (전기/수도/가스...) with latest month = current.
            try:
                data["energy"] = await self.api.get_energy_towmond()
            except ShomeConnectionError:
                pass
            try:
                data["expense"] = await self.api.get_expense()
            except ShomeConnectionError:
                pass

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
