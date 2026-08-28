"""Select platform for sHome home mode (외출/재실/방범)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ShomeConfigEntry
from .const import DOMAIN
from .coordinator import ShomeCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.data.get("home_mode", {}).get("modeList"):
        async_add_entities([ShomeHomeMode(coordinator)])


class ShomeHomeMode(CoordinatorEntity[ShomeCoordinator], SelectEntity):
    """홈모드 select."""

    _attr_has_entity_name = True
    _attr_name = "홈모드"
    _attr_icon = "mdi:home-account"

    def __init__(self, coordinator: ShomeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_home_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="sHome",
            manufacturer="Samsung SDS / Zigbang",
        )

    @property
    def _mode_list(self) -> list[dict]:
        return self.coordinator.data.get("home_mode", {}).get("modeList", []) or []

    def _code_to_name(self, code: str) -> str | None:
        for m in self._mode_list:
            if str(m.get("code")) == str(code):
                return m.get("name")
        return None

    def _name_to_code(self, name: str) -> str | None:
        for m in self._mode_list:
            if m.get("name") == name:
                return str(m.get("code"))
        return None

    @property
    def options(self) -> list[str]:
        return [m.get("name") for m in self._mode_list if m.get("name")]

    @property
    def current_option(self) -> str | None:
        state = self.coordinator.data.get("home_mode", {}).get("state")
        return self._code_to_name(state)

    async def async_select_option(self, option: str) -> None:
        code = self._name_to_code(option)
        if code is None:
            return
        res = await self.coordinator.api.set_home_mode(code)
        # reflect immediately
        hm = self.coordinator.data.setdefault("home_mode", {})
        hm["state"] = str(res.get("state", code)) if isinstance(res, dict) else code
        self.async_write_ha_state()
        self.coordinator.activate_fast_poll()
