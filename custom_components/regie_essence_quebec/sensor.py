"""Sensor platform for Régie Essence Québec."""
import logging
import re
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import RegieEssenceCoordinator

_LOGGER = logging.getLogger(__name__)

FUEL_TYPES = {
    "regular": {"name": "Ordinaire", "icon": "mdi:gas-station", "gas_types": ["Régulier", "Regulier", "Ordinaire"]},
    "super": {"name": "Super", "icon": "mdi:gas-station-outline", "gas_types": ["Super", "Premium", "Suprême"]},
    "diesel": {"name": "Diesel", "icon": "mdi:truck", "gas_types": ["Diesel", "Diésel"]},
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RegieEssenceCoordinator = hass.data[DOMAIN][entry.entry_id]
    configured_stations = entry.options.get("stations", [])
    
    sensors = []
    for address in configured_stations:
        for fuel_id, fuel_info in FUEL_TYPES.items():
            sensors.append(FuelPriceSensor(coordinator, entry, fuel_id, fuel_info, address))
        
    async_add_entities(sensors)

class FuelPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True 
    _attr_native_unit_of_measurement = "¢/L"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RegieEssenceCoordinator, entry: ConfigEntry, fuel_id: str, fuel_info: dict, address: str):
        super().__init__(coordinator)
        self._entry = entry
        self._fuel_id = fuel_id
        self._fuel_info = fuel_info
        self._address = address
        
        self._attr_name = fuel_info["name"]
        self._attr_icon = fuel_info["icon"]
        # Make the unique ID strictly tied to the specific address
        self._attr_unique_id = f"{entry.entry_id}_{address}_{fuel_id}"

    @property
    def device_info(self) -> DeviceInfo:
        station = self._station()
        brand = "Station Service"
        name = self._address
        
        if station:
            brand = station.get("brand", brand)
            name = f"{brand} ({self._address})"
            
        return DeviceInfo(
            identifiers={(DOMAIN, self._address)}, # This ensures each address gets its own Device card
            name=name,
            manufacturer=brand,
            via_device=(DOMAIN, self._entry.entry_id) # Ties it visually to the Hub
        )

    @property
    def native_value(self) -> float | None:
        station = self._station()
        if not station or "Prices" not in station:
            return None

        for price_item in station.get("Prices", []):
            actual_type = price_item.get("GasType", "").strip().lower()
            target_types = [t.lower() for t in self._fuel_info["gas_types"]]
            
            if actual_type in target_types:
                raw_price = str(price_item.get("Price", ""))
                match = re.search(r"([\d\.]+)", raw_price)
                if match: return float(match.group(1))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station()
        if not station: return {}
        return {
            "station_name": station.get("Name"),
            "address": station.get("Address"),
            "region": station.get("Region"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
        }

    def _station(self) -> dict | None:
        if self.coordinator.data is None: return None
        return self.coordinator.data.get(self._address)
