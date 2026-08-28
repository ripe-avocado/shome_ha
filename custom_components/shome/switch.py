"""Switch platform for sHome (퇴실스위치 일괄소등 os / 일괄조명 alo)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShomeConfigEntry
from .const import DEV_OUTSWITCH, DOMAIN
from .coordinator import ShomeCoordinator
from .entity import ShomeDeviceEntity
from .helpers import device_name, inventory_by_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    inv = inventory_by_id(coordinator)
    entities: list[SwitchEntity] = [
        ShomeOutSwitch(coordinator, DEV_OUTSWITCH, addr,
                       device_name(inv, "os", addr, f"퇴실스위치 {addr}"))
        for addr in coordinator.data.get("devices", {}).get(DEV_OUTSWITCH, {})
    ]
    # 스마트콘센트/대기전력 (legacy 세대, 실험적) — thngModelTypeName에 '콘센트' 포함
    for dev in coordinator.data.get("legacy", []) or []:
        if not isinstance(dev, dict):
            continue
        name = (dev.get("thngModelTypeName") or "") + (dev.get("nickname") or "")
        thng = dev.get("thngId") or dev.get("endpoint")
        if thng and ("콘센트" in name or "대기전력" in name):
            entities.append(ShomeLegacyConcent(coordinator, str(thng), dev.get("nickname")))
    async_add_entities(entities)


class ShomeOutSwitch(ShomeDeviceEntity, SwitchEntity):
    """퇴실스위치 — 일괄소등(jm00)만 제어. 가스밸브(gv01)/소화기(fe01)는 안전상 값을 보존한다."""

    _attr_name = "일괄소등"
    _attr_icon = "mdi:lightbulb-group-off"

    @property
    def is_on(self) -> bool | None:
        v = self._state.get("jm00")
        return None if v is None else str(v) == "1"

    def _preserve(self, key: str) -> str:
        """gv01/fe01: 현재값 보존. 값이 없으면 '1'(열림) — 가스/소화기를 절대 잠그지 않음."""
        v = self._state.get(key)
        return str(v) if v in ("0", "1") else "1"

    async def _set(self, jm00: str) -> None:
        res = await self.coordinator.api.set_outswitch(
            self._address, jm00, self._preserve("gv01"), self._preserve("fe01")
        )
        self._apply(res)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set("1")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set("0")


class ShomeLegacyConcent(CoordinatorEntity[ShomeCoordinator], SwitchEntity):
    """스마트콘센트/대기전력 (legacy 세대). ⚠ 실험적·미검증 — /v16/settings/smartConcent/{thngId}/{on|off}."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:power-socket-kr"

    def __init__(self, coordinator: ShomeCoordinator, thng_id: str, nickname: str | None) -> None:
        super().__init__(coordinator)
        self._thng = thng_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_concent_{thng_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_concent_{thng_id}")},
            name=nickname or f"스마트콘센트 {thng_id}",
            manufacturer="Samsung SDS / Zigbang",
            model="smartConcent",
        )

    def _dev(self) -> dict:
        for d in self.coordinator.data.get("legacy", []) or []:
            if isinstance(d, dict) and str(d.get("thngId") or d.get("endpoint")) == self._thng:
                return d
        return {}

    @property
    def is_on(self) -> bool | None:
        v = self._dev().get("onoff")
        if v is None:
            return None
        return str(v).lower() in ("on", "1", "true")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.api.legacy_concent_onoff(self._thng, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.api.legacy_concent_onoff(self._thng, False)
        await self.coordinator.async_request_refresh()
