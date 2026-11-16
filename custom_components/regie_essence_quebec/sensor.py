"""Sensor platform for Régie Essence Québec."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DATA_COORDINATOR, DOMAIN, TREND_STABLE, TRENDS
from .coordinator import RegieEssenceCoordinator
from .helpers import find_price_item, get_city, parse_price

FUEL_TYPES: dict[str, dict[str, str]] = {
    "regular": {"name": "Ordinaire", "icon": "mdi:gas-station"},
    "super": {"name": "Super", "icon": "mdi:gas-station-outline"},
    "diesel": {"name": "Diesel", "icon": "mdi:truck"},
}

TREND_ICONS = {
    "up": "mdi:trending-up",
    "down": "mdi:trending-down",
    "stable": "mdi:trending-neutral",
}
TREND_ARROWS = {"up": "📈", "down": "📉", "stable": "➖"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: RegieEssenceCoordinator = hass.data[DOMAIN][DATA_COORDINATOR]

    sensors: list[SensorEntity] = []
    for fuel_id, fuel_info in FUEL_TYPES.items():
        sensors.append(FuelPriceSensor(coordinator, entry, fuel_id, fuel_info))
        sensors.append(FuelTrendSensor(coordinator, entry, fuel_id, fuel_info))
    async_add_entities(sensors)


class StationEntity(CoordinatorEntity[RegieEssenceCoordinator]):
    """Common logic for entities attached to one monitored station."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RegieEssenceCoordinator,
        entry: ConfigEntry,
        fuel_id: str,
        fuel_info: dict[str, str],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._address: str = entry.data.get(CONF_ADDRESS, "")
        self._fuel_id = fuel_id
        self._fuel_info = fuel_info

    def _station(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._address)

    def _price_item(self) -> dict[str, Any] | None:
        return find_price_item(self._station(), self._fuel_id)

    @property
    def available(self) -> bool:
        return super().available and self._station() is not None

    @property
    def device_info(self) -> DeviceInfo:
        station = self._station()
        brand = "Régie Essence Québec"
        name = self._address or "Station Inconnue"
        if station:
            brand = station.get("brand") or brand
            name = f"{brand} - {get_city(self._address)}"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer=brand,
            model="Station Service",
        )


class FuelPriceSensor(StationEntity, SensorEntity):
    """Price of one fuel at the monitored station."""

    _attr_native_unit_of_measurement = "¢/L"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, fuel_id, fuel_info) -> None:
        super().__init__(coordinator, entry, fuel_id, fuel_info)
        self._attr_name = fuel_info["name"]
        self._attr_icon = fuel_info["icon"]
        self._attr_unique_id = f"{entry.entry_id}_{fuel_id}"

    @property
    def native_value(self) -> float | None:
        item = self._price_item()
        return parse_price(item.get("Price")) if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station()
        if not station:
            return {}

        attrs: dict[str, Any] = {
            "station_name": station.get("Name"),
            "address": station.get("Address"),
            "region": station.get("Region"),
            "status": station.get("Status"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
        }
        item = self._price_item()
        if item:
            tendency = item.get("Tendency", TREND_STABLE)
            attrs["tendency"] = tendency
            attrs["trend_arrow"] = TREND_ARROWS.get(tendency, "➖")
            attrs["is_available"] = item.get("IsAvailable")
        return attrs


class FuelTrendSensor(StationEntity, SensorEntity):
    """Direction of the last price change (up / down / stable)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = TRENDS
    _attr_translation_key = "trend"

    def __init__(self, coordinator, entry, fuel_id, fuel_info) -> None:
        super().__init__(coordinator, entry, fuel_id, fuel_info)
        self._attr_name = f"Tendance {fuel_info['name']}"
        self._attr_unique_id = f"{entry.entry_id}_{fuel_id}_trend"

    @property
    def native_value(self) -> str:
        item = self._price_item()
        trend = item.get("Tendency", TREND_STABLE) if item else TREND_STABLE
        return trend if trend in TRENDS else TREND_STABLE

    @property
    def icon(self) -> str:
        return TREND_ICONS.get(self.native_value, "mdi:trending-neutral")
