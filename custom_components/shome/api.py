"""Async client for the sHome (Samsung SDS / Zigbang IHP) cloud API.

Reverse-engineered from the sHome Android app (com.ih.app.svc.v15, v3.1.48).
See PROTOCOL.md for the full specification.

Request signing (every call):
    createDate = utcnow "%Y%m%d%H%M%S"
    values     = "".join(str(v) for v in querymap.values())   # createDate included
    hashData   = sha512_hex(SALT + "".join(path_args) + values)
"""
from __future__ import annotations

import datetime
import hashlib
import logging
from typing import Any

import aiohttp

from .const import (
    APP_VERSION,
    DEFAULT_BASE_URL,
    DEFAULT_LANGUAGE,
    OS_TYPE,
    SALT,
)

_LOGGER = logging.getLogger(__name__)


class ShomeError(Exception):
    """Base error."""


class ShomeAuthError(ShomeError):
    """Authentication failed (bad credentials, locked, etc.)."""

    def __init__(self, message: str, result: int | None = None, lock_minutes: int | None = None):
        super().__init__(message)
        self.result = result
        self.lock_minutes = lock_minutes


class ShomeConnectionError(ShomeError):
    """Network/HTTP error."""


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")


def _sha512_hex(s: str) -> str:
    return format(int.from_bytes(hashlib.sha512(s.encode("utf-8")).digest(), "big"), "0128x")


# LoginVO.result codes (from LoginActivity string resources)
LOGIN_OK = 0
LOGIN_LIMITED = 1            # login_error_case1: locked %s minutes
LOGIN_PW_5_TIMES = 2        # password_error_five_times: locked 10 minutes
LOGIN_PW_WRONG = 3          # password_error: check ID/password
LOGIN_DEVICE_LIMIT = 4      # login_error_case4: 8-device limit exceeded
LOGIN_REJOIN = 5            # needs re-join / password reset


class ShomeApi:
    """Talks to the sHome cloud REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_id: str,
        password: str,
        device_id: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._password = password
        self._device_id = device_id
        self._base = base_url.rstrip("/") + "/"
        self._language = language
        self._token: str | None = None
        self.login_vo: dict[str, Any] = {}

    # -- properties from last login -----------------------------------------
    @property
    def token(self) -> str | None:
        return self._token

    @property
    def home_id(self) -> str | None:
        return self.login_vo.get("homeId")

    @property
    def serial_number(self) -> str | None:
        return self.login_vo.get("serialNumber")

    @property
    def biz_id(self) -> str | None:
        return self.login_vo.get("bizId")

    # -- signing ------------------------------------------------------------
    def _query_map(self, base_map: dict | None = None, *args: Any) -> dict:
        m: dict[str, Any] = dict(base_map or {})
        m["createDate"] = _utcnow()
        values = "".join(str(v) for v in m.values())
        m["hashData"] = _sha512_hex(SALT + "".join(str(a) for a in args) + values)
        return m

    def _headers(self) -> dict:
        h = {
            "X-APP-VERSION": APP_VERSION,
            "X-OS-TYPE": OS_TYPE,
            "X-OS-VERSION": "13",
            "X-DEVICE-MODEL": "shome-ha",
            "Accept-Language": "ko",
        }
        if self._token:
            h["Authorization"] = "Bearer " + self._token
        return h

    async def _request(self, method: str, path: str, params: dict) -> Any:
        url = self._base + path.lstrip("/")
        try:
            async with self._session.request(
                method, url, params=params, headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise ShomeAuthError(f"401 unauthorized: {text[:200]}")
                if resp.status >= 400:
                    raise ShomeConnectionError(f"HTTP {resp.status}: {text[:200]}")
                try:
                    return await resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    return text
        except aiohttp.ClientError as err:
            raise ShomeConnectionError(str(err)) from err

    async def _get_auth(self, path: str, *args: Any, base_map: dict | None = None) -> Any:
        """Authenticated GET on a /v18/mhps/auth path with signing."""
        return await self._request("GET", path, self._query_map(base_map, *args))

    # -- login --------------------------------------------------------------
    async def login(self) -> dict:
        # The app sends SHA-512 hex of the raw password, not plaintext.
        # (LoginActivity: w0(id, e.a(pw)), e.a = SHA-512 hex). hashData uses the hashed value too.
        pw_hashed = _sha512_hex(self._password)
        cd = _utcnow()
        sig = _sha512_hex(
            SALT + self._user_id + pw_hashed + self._device_id + "" + self._language + cd
        )
        params = {
            "userId": self._user_id,
            "password": pw_hashed,
            "mobileDeviceIdno": self._device_id,
            "appRegstId": "",
            "language": self._language,
            "createDate": cd,
            "hashData": sig,
        }
        vo = await self._request("PUT", "v18/users/login", params)
        if not isinstance(vo, dict):
            raise ShomeAuthError(f"unexpected login response: {vo!r}")
        self.login_vo = vo
        result = vo.get("result")
        token = vo.get("accessToken")
        if token and result in (LOGIN_OK, None):
            self._token = token
            return vo
        # map error
        lock = vo.get("loginLimitTimeCeil")
        if result == LOGIN_PW_WRONG:
            raise ShomeAuthError("아이디 또는 비밀번호가 올바르지 않습니다.", result)
        if result == LOGIN_PW_5_TIMES:
            raise ShomeAuthError(
                f"비밀번호 5회 오류로 계정이 잠겼습니다. 약 {lock or 10}분 후 다시 시도하세요.",
                result, lock,
            )
        if result == LOGIN_LIMITED:
            raise ShomeAuthError(f"로그인 제한 상태입니다. 약 {lock}분 후 다시 시도하세요.", result, lock)
        if result == LOGIN_DEVICE_LIMIT:
            raise ShomeAuthError("등록 가능한 모바일 기기(8대)를 초과했습니다.", result)
        if result == LOGIN_REJOIN:
            raise ShomeAuthError("재가입 또는 비밀번호 재설정이 필요한 계정입니다.", result)
        if token:  # unknown result but token present
            self._token = token
            return vo
        raise ShomeAuthError(f"로그인 실패 (result={result})", result)

    async def async_ensure_token(self) -> None:
        if not self._token:
            await self.login()

    # -- monitoring ---------------------------------------------------------
    async def get_all_list(self) -> dict:
        return await self._get_auth("v18/mhps/auth/device/all_list")

    async def get_all_state(self, dtype: str) -> dict:
        return await self._get_auth(f"v18/mhps/auth/device/{dtype}/all_state")

    async def get_state(self, dtype: str, address: str) -> dict:
        return await self._get_auth(f"v18/mhps/auth/device/{dtype}/{address}/state", address)

    # -- control ------------------------------------------------------------
    async def set_power(self, dtype: str, address: str, power: str) -> dict:
        return await self._get_auth(
            f"v18/mhps/auth/device/{dtype}/{address}/power/{power}", address, power
        )

    async def set_function(self, dtype: str, address: str, level: str) -> dict:
        """Dimming/brightness (light, dimming) via /function/{level}."""
        return await self._get_auth(
            f"v18/mhps/auth/device/{dtype}/{address}/function/{level}", address, level
        )

    async def set_one_function(self, dtype: str, address: str, name: str, value: str) -> dict:
        """aircon/boiler/fan one_function/{name}/{value}."""
        return await self._get_auth(
            f"v18/mhps/auth/device/{dtype}/{address}/one_function/{name}/{value}",
            address, name, value,
        )

    async def set_boiler_bl_power(self, address: str, power_room: str, power_water: str) -> dict:
        return await self._get_auth(
            f"v18/mhps/auth/device/boiler/bl/{address}/power/{power_room}/{power_water}",
            address, power_room, power_water,
        )

    async def set_outswitch(self, address: str, jm00: str, gv01: str, fe01: str) -> dict:
        return await self._get_auth(
            f"v18/mhps/auth/device/outswitch/{address}/power/{jm00}/{gv01}/{fe01}",
            address, jm00, gv01, fe01,
        )

    async def set_all_power(self, dtype: str, power: str) -> dict:
        return await self._get_auth(
            f"v18/mhps/auth/device/{dtype}/all_power/{power}", power
        )

    # -- home mode ----------------------------------------------------------
    async def get_home_mode(self) -> dict:
        return await self._get_auth("v18/mhps/auth/homemode/list_and_state")

    async def set_home_mode(self, state: str) -> dict:
        return await self._get_auth(
            f"v18/mhps/auth/homemode/check_and_control/{state}", state
        )

    # -- contents (energy / expense / etc.) --------------------------------
    async def get_energy_recently(self) -> dict:
        return await self._get_auth("v18/mhps/auth/contents/norems/energy/recently")

    async def get_energy_towmond(self) -> dict:
        return await self._get_auth("v18/mhps/auth/contents/norems/energy/towmond")

    async def get_expense(self) -> dict:
        return await self._get_auth("v18/mhps/auth/contents/expense/towmond")

    async def get_visit_all(self) -> dict:
        return await self._get_auth("v18/mhps/auth/contents/visit/all_list")

    async def get_visit_recently(self) -> dict:
        return await self._get_auth("v18/mhps/auth/contents/visit/recently")

    async def get_parcel_all(self) -> dict:
        return await self._get_auth("v18/mhps/auth/contents/parcel/all")

    async def get_maindata(self) -> dict:
        return await self._get_auth("v18/mhps/auth/service/app/maindata")

    async def get_menu(self) -> dict:
        return await self._get_auth("v18/mhps/auth/service/get_menu")

    # -- MHPS vs legacy detection ------------------------------------------
    @property
    def is_mhps(self) -> bool:
        v = self.login_vo.get("isMhpsUser")
        return str(v) == "1"

    @property
    def wallpad_id(self) -> str | None:
        """Legacy wallPadId = ihdId (SettingApp.G())."""
        return self.login_vo.get("ihdId") or None

    # -- LEGACY (구형 세대) API — /v16/settings/* -------------------------
    # 실험적/미검증: MHPS가 아닌 세대에서만 사용. 이 계정(MHPS)에선 500이 나므로 테스트 불가.
    async def get_legacy_devices(self, wallpad_id: str | None = None) -> dict:
        """GET /v16/settings/{wallPadId}/devices/ → DeviceControlVo (모든 기기 통합 목록)."""
        wp = wallpad_id or self.wallpad_id
        if not wp:
            raise ShomeError("legacy wallPadId(ihdId) unavailable")
        return await self._get_auth(f"v16/settings/{wp}/devices/", wp)

    async def legacy_gasvalve_close(self, thng_id: str) -> dict:
        """PUT /v16/settings/gasvalves/{thngId}/closing/ — 가스밸브 닫기(안전상 닫기만)."""
        return await self._request(
            "PUT", f"v16/settings/gasvalves/{thng_id}/closing/",
            self._query_map(None, thng_id),
        )

    async def legacy_concent_onoff(self, thng_id: str, on: bool) -> dict:
        """PUT /v16/settings/smartConcent/{thngId}/{onoff} — 스마트콘센트 on/off."""
        onoff = "on" if on else "off"
        return await self._request(
            "PUT", f"v16/settings/smartConcent/{thng_id}/{onoff}",
            self._query_map(None, thng_id, onoff),
        )
