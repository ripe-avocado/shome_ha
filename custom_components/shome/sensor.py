"""Sensor platform for sHome (에너지: 전기/수도/가스/온수/난방, 관리비)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ShomeConfigEntry
from .const import DOMAIN
from .coordinator import ShomeCoordinator

# 실내환경(legacy) 측정 항목: (json key, 이름, unit, device_class)
ENV_METRICS = [
    ("temperature", "온도", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    ("humidity", "습도", PERCENTAGE, SensorDeviceClass.HUMIDITY),
    ("co2", "CO2", CONCENTRATION_PARTS_PER_MILLION, SensorDeviceClass.CO2),
    ("fineDust", "미세먼지", CONCENTRATION_MICROGRAMS_PER_CUBIC_METER, SensorDeviceClass.PM25),
]


@dataclass(frozen=True)
class EnergyKind:
    name: str
    unit: str | None
    device_class: SensorDeviceClass | None
    icon: str


# energyType 매핑 (앱 shnEnergyReportActivity.O 기준):
#   1=전기 kWh, 2=수도 ㎥(≈톤), 3=가스 ㎥, 4=난방 ㎥, 5=온수 ㎥(≈톤; 월패드는 물을 톤으로 표기)
ENERGY_KINDS: dict[str, EnergyKind] = {
    "1": EnergyKind("전기 사용량", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, "mdi:flash"),
    "2": EnergyKind("수도 사용량", UnitOfVolume.CUBIC_METERS, SensorDeviceClass.WATER, "mdi:water"),
    "3": EnergyKind("가스 사용량", UnitOfVolume.CUBIC_METERS, SensorDeviceClass.GAS, "mdi:fire"),
    "4": EnergyKind("난방 사용량", UnitOfVolume.CUBIC_METERS, None, "mdi:radiator"),
    "5": EnergyKind("온수 사용량", UnitOfVolume.CUBIC_METERS, SensorDeviceClass.WATER, "mdi:water-thermometer"),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ShomeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    energy = coordinator.data.get("energy") or {}
    for item in energy.get("energyList", []) or []:
        etype = str(item.get("energyType"))
        if etype in ENERGY_KINDS:
            entities.append(ShomeEnergySensor(coordinator, etype))

    # 관리비 sensor (지원 단지에서 expense 데이터가 있을 때만 생성)
    expense = coordinator.data.get("expense")
    if isinstance(expense, dict) and (expense.get("monthList") or []):
        entities.append(ShomeExpenseSensor(coordinator))

    # 실내환경 센서 (legacy 세대, 실험적): temperature/humidity/co2/fineDust 필드가 있는 기기
    for dev in coordinator.data.get("legacy", []) or []:
        if not isinstance(dev, dict):
            continue
        thng = dev.get("thngId") or dev.get("endpoint")
        if not thng:
            continue
        for key, label, unit, dclass in ENV_METRICS:
            if dev.get(key) not in (None, ""):
                entities.append(
                    ShomeLegacyEnvSensor(coordinator, str(thng), dev.get("nickname"),
                                         key, label, unit, dclass)
                )
    async_add_entities(entities)



class ShomeExpenseSensor(CoordinatorEntity[ShomeCoordinator], SensorEntity):
    """관리비 (최신월 합계). 항목별 내역은 속성으로."""

    _attr_has_entity_name = True
    _attr_name = "관리비"
    _attr_icon = "mdi:receipt-text"
    _attr_native_unit_of_measurement = "원"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: ShomeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_expense"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_energy")},
            name="sHome 에너지",
            manufacturer="Samsung SDS / Zigbang",
        )

    def _latest(self) -> dict[str, Any]:
        exp = self.coordinator.data.get("expense") or {}
        months = exp.get("monthList") or []
        return months[-1] if months else {}

    @staticmethod
    def _num(v) -> float | None:
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self) -> float | None:
        fees = self._latest().get("feeList") or []
        total = 0.0
        found = False
        for it in fees:
            n = self._num(it.get("value"))
            if n is not None:
                total += n
                found = True
        return total if found else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        m = self._latest()
        attrs: dict[str, Any] = {}
        if m.get("year") and m.get("month"):
            attrs["기준월"] = f"{m['year']}-{int(m['month']):02d}"
        for it in (m.get("feeList") or []):
            if it.get("name"):
                attrs[str(it["name"])] = it.get("value")
        return attrs


class ShomeEnergySensor(CoordinatorEntity[ShomeCoordinator], SensorEntity):
    """이번 달 누적 사용량 (매월 0으로 리셋). total_increasing → HA가 월간 리셋을 자동 감지."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ShomeCoordinator, etype: str) -> None:
        super().__init__(coordinator)
        self._etype = etype
        kind = ENERGY_KINDS[etype]
        self._attr_name = kind.name
        self._attr_native_unit_of_measurement = kind.unit
        self._attr_device_class = kind.device_class
        self._attr_icon = kind.icon
        self._attr_unique_id = f"{coordinator.entry.entry_id}_energy_{etype}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_energy")},
            name="sHome 에너지",
            manufacturer="Samsung SDS / Zigbang",
        )

    def _item(self) -> dict[str, Any]:
        energy = self.coordinator.data.get("energy") or {}
        for it in energy.get("energyList", []) or []:
            if str(it.get("energyType")) == self._etype:
                return it
        return {}

    def _latest_month(self) -> dict[str, Any]:
        months = self._item().get("monthList") or []
        return months[-1] if months else {}

    @property
    def native_value(self) -> float | None:
        v = self._latest_month().get("usageAmount")
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        m = self._latest_month()
        attrs: dict[str, Any] = {}
        if m.get("year") and m.get("month"):
            attrs["기준월"] = f"{m['year']}-{int(m['month']):02d}"
        if m.get("prevUsageAmount") is not None:
            attrs["전월"] = m["prevUsageAmount"]
        if m.get("expectUsageAmount") is not None:
            attrs["예상"] = m["expectUsageAmount"]
        return attrs


class ShomeLegacyEnvSensor(CoordinatorEntity[ShomeCoordinator], SensorEntity):
    """실내환경 센서 (legacy 세대) — 온도/습도/CO2/미세먼지. ⚠ 실험적·미검증(레거시 세대 테스트 필요)."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ShomeCoordinator, thng_id: str, nickname: str | None,
                 key: str, label: str, unit: str, dclass) -> None:
        super().__init__(coordinator)
        self._thng = thng_id
        self._key = key
        self._attr_name = label
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = dclass
        self._attr_unique_id = f"{coordinator.entry.entry_id}_env_{thng_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_env_{thng_id}")},
            name=nickname or f"실내환경 {thng_id}",
            manufacturer="Samsung SDS / Zigbang",
            model="environment-sensor",
        )

    def _dev(self) -> dict:
        for d in self.coordinator.data.get("legacy", []) or []:
            if isinstance(d, dict) and str(d.get("thngId") or d.get("endpoint")) == self._thng:
                return d
        return {}

    @property
    def native_value(self) -> float | None:
        v = self._dev().get(self._key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
