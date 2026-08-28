"""Climate platform for sHome (난방 boiler bl/br, 냉방 aircon)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShomeConfigEntry
from .const import DEV_AIRCON, DEV_BOILER_BL, DEV_BOILER_BR
from .entity import ShomeDeviceEntity
from .helpers import device_name, inventory_by_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    inv = inventory_by_id(coordinator)
    entities: list[ClimateEntity] = []
    devices = coordinator.data.get("devices", {})
    for addr in devices.get(DEV_BOILER_BL, {}):
        entities.append(ShomeBoilerBl(coordinator, DEV_BOILER_BL, addr,
                                      device_name(inv, "bl", addr, f"난방 {addr}")))
    for addr in devices.get(DEV_BOILER_BR, {}):
        entities.append(ShomeBoilerBr(coordinator, DEV_BOILER_BR, addr,
                                      device_name(inv, "br", addr, f"난방 {addr}")))
    for addr in devices.get(DEV_AIRCON, {}):
        entities.append(ShomeAircon(coordinator, DEV_AIRCON, addr,
                                    device_name(inv, "ac", addr, f"냉방 {addr}")))
    async_add_entities(entities)


def _to_int(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class ShomeBoilerBl(ShomeDeviceEntity, ClimateEntity):
    """난방 bl — 난방 전용(온수는 별도 표기 없음)."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = 5
    _attr_max_temp = 40
    _attr_target_temperature_step = 1

    @property
    def current_temperature(self) -> float | None:
        return _to_int(self._state.get("heatingRoom"))

    @property
    def target_temperature(self) -> float | None:
        return _to_int(self._state.get("heatingDesireRoom"))

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if str(self._state.get("powerRoom")) == "1" else HVACMode.OFF

    def _water(self) -> str:
        w = self._state.get("powerWater")
        return "1" if str(w) == "1" else "0"

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        power = "1" if hvac_mode == HVACMode.HEAT else "0"
        res = await self.coordinator.api.set_boiler_bl_power(self._address, power, self._water())
        self._apply(res)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        res = await self.coordinator.api.set_one_function(
            self._dtype, self._address, "heatingdesireroom", str(int(temp))
        )
        self._apply(res)


class ShomeBoilerBr(ShomeDeviceEntity, ClimateEntity):
    """난방 br."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = 10
    _attr_max_temp = 40
    _attr_target_temperature_step = 1

    @property
    def current_temperature(self) -> float | None:
        return _to_int(self._state.get("heatingRoom"))

    @property
    def target_temperature(self) -> float | None:
        return _to_int(self._state.get("heatingDesireRoom"))

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if str(self._state.get("power")) == "1" else HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        power = "1" if hvac_mode == HVACMode.HEAT else "0"
        res = await self.coordinator.api.set_power(self._dtype, self._address, power)
        self._apply(res)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        res = await self.coordinator.api.set_one_function(
            self._dtype, self._address, "heatingdesireroom", str(int(temp))
        )
        self._apply(res)


class ShomeAircon(ShomeDeviceEntity, ClimateEntity):
    """냉방 aircon."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = 18
    _attr_max_temp = 30
    _attr_target_temperature_step = 1

    @property
    def current_temperature(self) -> float | None:
        return _to_int(self._state.get("currentTemp"))

    @property
    def target_temperature(self) -> float | None:
        return _to_int(self._state.get("desireTemp"))

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.COOL if str(self._state.get("power")) == "1" else HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        power = "1" if hvac_mode == HVACMode.COOL else "0"
        res = await self.coordinator.api.set_power(self._dtype, self._address, power)
        self._apply(res)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        res = await self.coordinator.api.set_one_function(
            self._dtype, self._address, "desiretemp", str(int(temp))
        )
        self._apply(res)
