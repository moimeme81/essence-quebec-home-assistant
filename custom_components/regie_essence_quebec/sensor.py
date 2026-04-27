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

from .const import DOMAIN, CONF_ADDRESS
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
    """Set up the sensor platform."""
    coordinator: RegieEssenceCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    sensors = []
    for fuel_id, fuel_info in FUEL_TYPES.items():
        # Entité 1 : Le prix
        sensors.append(FuelPriceSensor(coordinator, entry, fuel_id, fuel_info))
        # Entité 2 : La tendance
        sensors.append(FuelTrendSensor(coordinator, entry, fuel_id, fuel_info))
        
    async_add_entities(sensors)

class FuelPriceSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Fuel Price Sensor."""
    
    _attr_has_entity_name = True 
    _attr_native_unit_of_measurement = "¢/L"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RegieEssenceCoordinator, entry: ConfigEntry, fuel_id: str, fuel_info: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._fuel_id = fuel_id
        self._fuel_info = fuel_info
        
        self._attr_name = fuel_info["name"]
        self._attr_icon = fuel_info["icon"]
        self._attr_unique_id = f"{entry.entry_id}_{fuel_id}"

    def _get_city(self, address: str) -> str:
        if not address: return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    def _station(self) -> dict | None:
        """Helper to find the specific station data in the coordinator dictionary."""
        if self.coordinator.data is None:
            return None
        address = self._entry.data.get(CONF_ADDRESS)
        return self.coordinator.data.get(address)

    def _get_price_item(self) -> dict | None:
        """Helper to find the specific fuel type block in the station data."""
        station = self._station()
        if not station or "Prices" not in station:
            return None

        for price_item in station.get("Prices", []):
            actual_type = str(price_item.get("GasType", "")).strip().lower()
            target_types = [t.lower() for t in self._fuel_info["gas_types"]]
            
            if actual_type in target_types:
                return price_item
        return None

    @property
    def device_info(self) -> DeviceInfo:
        station = self._station()
        address = self._entry.data.get(CONF_ADDRESS, "Station Inconnue")
        brand = "Régie Essence Québec"
        name = address
        
        if station:
            brand = station.get("brand", brand)
            name = f"{brand} - {self._get_city(address)}"
            
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer=brand,
            model="Station Service",
        )

    @property
    def native_value(self) -> float | None:
        price_item = self._get_price_item()
        if price_item:
            raw_price = str(price_item.get("Price", ""))
            match = re.search(r"([\d\.]+)", raw_price)
            if match:
                return float(match.group(1))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station()
        if not station:
            return {}
            
        attrs = {
            "station_name": station.get("Name"),
            "address": station.get("Address"),
            "region": station.get("Region"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
        }
        
        # On garde aussi la tendance en attribut au cas où
        price_item = self._get_price_item()
        if price_item:
            tendency = price_item.get("Tendency", "stable")
            attrs["tendency"] = tendency
            arrows = {"up": "📈", "down": "📉", "stable": "➖"}
            attrs["trend_arrow"] = arrows.get(tendency, "➖")
            
        return attrs

class FuelTrendSensor(CoordinatorEntity, SensorEntity):
    """Capteur dédié à la tendance du prix (Hausse/Baisse)."""
    
    _attr_has_entity_name = True 

    def __init__(self, coordinator: RegieEssenceCoordinator, entry: ConfigEntry, fuel_id: str, fuel_info: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._fuel_id = fuel_id
        self._fuel_info = fuel_info
        
        self._attr_name = f"Tendance {fuel_info['name']}"
        self._attr_unique_id = f"{entry.entry_id}_{fuel_id}_trend"

    def _get_city(self, address: str) -> str:
        if not address: return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    def _station(self) -> dict | None:
        if self.coordinator.data is None:
            return None
        address = self._entry.data.get(CONF_ADDRESS)
        return self.coordinator.data.get(address)

    @property
    def icon(self) -> str:
        arrows = {"up": "mdi:trending-up", "down": "mdi:trending-down", "stable": "mdi:trending-neutral"}
        return arrows.get(self.native_value, "mdi:trending-neutral")

    @property
    def native_value(self) -> str:
        station = self._station()
        if not station:
            return "stable"

        for price_item in station.get("Prices", []):
            actual_type = str(price_item.get("GasType", "")).strip().lower()
            target_types = [t.lower() for t in self._fuel_info["gas_types"]]
            if actual_type in target_types:
                return price_item.get("Tendency", "stable")
        return "stable"

    @property
    def device_info(self) -> DeviceInfo:
        station = self._station()
        address = self._entry.data.get(CONF_ADDRESS, "Station Inconnue")
        brand = "Régie Essence Québec"
        name = address
        
        if station:
            brand = station.get("brand", brand)
            name = f"{brand} - {self._get_city(address)}"
            
        # L'utilisation du même identifier relie cette entité au même appareil que le prix
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer=brand,
            model="Station Service",
        )
        sensors.append(FuelTrendSensor(coordinator, entry, fuel_id, fuel_info))
        
    async_add_entities(sensors)

class FuelPriceSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Fuel Price Sensor."""
    
    _attr_has_entity_name = True 
    _attr_native_unit_of_measurement = "¢/L"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RegieEssenceCoordinator, entry: ConfigEntry, fuel_id: str, fuel_info: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._fuel_id = fuel_id
        self._fuel_info = fuel_info
        
        self._attr_name = fuel_info["name"]
        self._attr_icon = fuel_info["icon"]
        self._attr_unique_id = f"{entry.entry_id}_{fuel_id}"

    def _get_city(self, address: str) -> str:
        if not address: return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    def _station(self) -> dict | None:
        """Helper to find the specific station data in the coordinator dictionary."""
        if self.coordinator.data is None:
            return None
        address = self._entry.data.get(CONF_ADDRESS)
        return self.coordinator.data.get(address)

    def _get_price_item(self) -> dict | None:
        """Helper to find the specific fuel type block in the station data."""
        station = self._station()
        if not station or "Prices" not in station:
            return None

        for price_item in station.get("Prices", []):
            actual_type = str(price_item.get("GasType", "")).strip().lower()
            target_types = [t.lower() for t in self._fuel_info["gas_types"]]
            
            if actual_type in target_types:
                return price_item
        return None

    @property
    def device_info(self) -> DeviceInfo:
        station = self._station()
        address = self._entry.data.get(CONF_ADDRESS, "Station Inconnue")
        brand = "Régie Essence Québec"
        name = address
        
        if station:
            brand = station.get("brand", brand)
            name = f"{brand} - {self._get_city(address)}"
            
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer=brand,
            model="Station Service",
        )

    @property
    def native_value(self) -> float | None:
        price_item = self._get_price_item()
        if price_item:
            raw_price = str(price_item.get("Price", ""))
            match = re.search(r"([\d\.]+)", raw_price)
            if match:
                return float(match.group(1))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station()
        if not station:
            return {}
            
        attrs = {
            "station_name": station.get("Name"),
            "address": station.get("Address"),
            "region": station.get("Region"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
        }
        
        # On garde aussi la tendance en attribut au cas où
        price_item = self._get_price_item()
        if price_item:
            tendency = price_item.get("Tendency", "stable")
            attrs["tendency"] = tendency
            arrows = {"up": "📈", "down": "📉", "stable": "➖"}
            attrs["trend_arrow"] = arrows.get(tendency, "➖")
            
        return attrs

class FuelTrendSensor(CoordinatorEntity, SensorEntity):
    """Capteur dédié à la tendance du prix (Hausse/Baisse)."""
    
    _attr_has_entity_name = True 

    def __init__(self, coordinator: RegieEssenceCoordinator, entry: ConfigEntry, fuel_id: str, fuel_info: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._fuel_id = fuel_id
        self._fuel_info = fuel_info
        
        self._attr_name = f"Tendance {fuel_info['name']}"
        self._attr_unique_id = f"{entry.entry_id}_{fuel_id}_trend"

    def _get_city(self, address: str) -> str:
        if not address: return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    def _station(self) -> dict | None:
        if self.coordinator.data is None:
            return None
        address = self._entry.data.get(CONF_ADDRESS)
        return self.coordinator.data.get(address)

    @property
    def icon(self) -> str:
        arrows = {"up": "mdi:trending-up", "down": "mdi:trending-down", "stable": "mdi:trending-neutral"}
        return arrows.get(self.native_value, "mdi:trending-neutral")

    @property
    def native_value(self) -> str:
        station = self._station()
        if not station:
            return "stable"

        for price_item in station.get("Prices", []):
            actual_type = str(price_item.get("GasType", "")).strip().lower()
            target_types = [t.lower() for t in self._fuel_info["gas_types"]]
            if actual_type in target_types:
                return price_item.get("Tendency", "stable")
        return "stable"

    @property
    def device_info(self) -> DeviceInfo:
        station = self._station()
        address = self._entry.data.get(CONF_ADDRESS, "Station Inconnue")
        brand = "Régie Essence Québec"
        name = address
        
        if station:
            brand = station.get("brand", brand)
            name = f"{brand} - {self._get_city(address)}"
            
        # L'utilisation du même identifier relie cette entité au même appareil que le prix
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer=brand,
            model="Station Service",
        )

class FuelPriceSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Fuel Price Sensor."""
    
    _attr_has_entity_name = True 
    _attr_native_unit_of_measurement = "¢/L"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RegieEssenceCoordinator, entry: ConfigEntry, fuel_id: str, fuel_info: dict):
        super().__init__(coordinator)
        self._entry = entry
        self._fuel_id = fuel_id
        self._fuel_info = fuel_info
        
        self._attr_name = fuel_info["name"]
        self._attr_icon = fuel_info["icon"]
        self._attr_unique_id = f"{entry.entry_id}_{fuel_id}"

    def _get_city(self, address: str) -> str:
        if not address: return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    def _station(self) -> dict | None:
        """Helper to find the specific station data in the coordinator dictionary."""
        if self.coordinator.data is None:
            return None
        address = self._entry.data.get(CONF_ADDRESS)
        return self.coordinator.data.get(address)

    def _get_price_item(self) -> dict | None:
        """Helper to find the specific fuel type block in the station data."""
        station = self._station()
        if not station or "Prices" not in station:
            return None

        for price_item in station.get("Prices", []):
            actual_type = str(price_item.get("GasType", "")).strip().lower()
            target_types = [t.lower() for t in self._fuel_info["gas_types"]]
            
            if actual_type in target_types:
                return price_item
        return None

    @property
    def device_info(self) -> DeviceInfo:
        station = self._station()
        address = self._entry.data.get(CONF_ADDRESS, "Station Inconnue")
        brand = "Régie Essence Québec"
        name = address
        
        if station:
            brand = station.get("brand", brand)
            name = f"{brand} - {self._get_city(address)}"
            
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer=brand,
            model="Station Service",
        )

    @property
    def native_value(self) -> float | None:
        price_item = self._get_price_item()
        if price_item:
            raw_price = str(price_item.get("Price", ""))
            match = re.search(r"([\d\.]+)", raw_price)
            if match:
                return float(match.group(1))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station()
        if not station:
            return {}
            
        attrs = {
            "station_name": station.get("Name"),
            "address": station.get("Address"),
            "region": station.get("Region"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
        }
        
        # Récupération et injection de la tendance (Tendency)
        price_item = self._get_price_item()
        if price_item:
            tendency = price_item.get("Tendency", "stable")
            attrs["tendency"] = tendency
            
            # Ajout d'un emoji visuel pour les cartes Lovelace
            arrows = {"up": "📈", "down": "📉", "stable": "➖"}
            attrs["trend_arrow"] = arrows.get(tendency, "➖")
            
        return attrs
