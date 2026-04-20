"""The Régie Essence Québec integration."""
from __future__ import annotations

import logging
import math
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.core import SupportsResponse

from .const import DOMAIN
from .coordinator import RegieEssenceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_FIND_CLOSEST = "find_closest_stations"
SERVICE_FIND_CLOSEST_SCHEMA = vol.Schema(
    {
        vol.Required("latitude"): vol.Coerce(float),
        vol.Required("longitude"): vol.Coerce(float),
        vol.Optional("limit", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
        vol.Optional("radius", default=10.0): vol.All(vol.Coerce(float), vol.Range(min=1, max=200)),
        vol.Optional("gas_type", default="Régulier"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from YAML (not used)."""
    hass.data.setdefault(DOMAIN, {})
    await _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Régie Essence Québec from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = RegieEssenceCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_FIND_CLOSEST):
        return

    async def find_closest_stations(call: ServiceCall) -> dict[str, Any]:
        raw_lat = call.data.get("latitude")
        raw_lon = call.data.get("longitude")
        limit = int(call.data.get("limit", 3))
        radius = float(call.data.get("radius", 10.0))
        gas_type = str(call.data.get("gas_type", "Régulier")).strip().lower()

        if raw_lat is None or raw_lon is None:
            raise ValueError("Could not read GPS coordinates.")

        lat = float(raw_lat)
        lon = float(raw_lon)

        if lat == 0 or lon == 0:
            raise ValueError("Latitude and longitude cannot be zero.")

        domain_data = hass.data.get(DOMAIN, {})
        if not domain_data:
            raise ValueError("No configured integration entry is available.")

        # Use any active coordinator's client to access shared API fetch logic.
        coordinator: RegieEssenceCoordinator = next(iter(domain_data.values()))
        stations = await coordinator._client.async_get_all_stations()
        valid_stations: list[dict[str, Any]] = []

        target_types = [gas_type]
        if gas_type in ["régulier", "regulier", "ordinaire"]:
            target_types = ["régulier", "regulier", "ordinaire"]
        elif gas_type in ["diesel", "diésel"]:
            target_types = ["diesel", "diésel"]

        for station in stations:
            s_lat = station.get("latitude", 0)
            s_lon = station.get("longitude", 0)
            if not s_lat or not s_lon:
                continue

            earth_radius_km = 6371.0
            dlat = math.radians(s_lat - lat)
            dlon = math.radians(s_lon - lon)
            
            a = (
                (math.sin(dlat / 2) ** 2)
                + math.cos(math.radians(lat))
                * math.cos(math.radians(s_lat))
                * (math.sin(dlon / 2) ** 2)
            )
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance_km = round(earth_radius_km * c, 2)

            if distance_km > radius:
                continue

            station_with_distance = dict(station)
            station_with_distance["distance_km"] = distance_km

            for price_item in station.get("Prices", []):
                actual_type = str(price_item.get("GasType", "")).strip().lower()
                if actual_type not in target_types:
                    continue

                raw_price = str(price_item.get("Price", ""))
                match = re.search(r"([\d\.]+)", raw_price)
                if not match:
                    continue

                station_with_distance["target_price"] = float(match.group(1))
                valid_stations.append(station_with_distance)
                break

        by_distance = sorted(valid_stations, key=lambda item: item.get("distance_km", 99999))
        by_price = sorted(
            valid_stations,
            key=lambda item: (item.get("target_price", 999.9), item.get("distance_km", 99999)),
         )

        return {"closest": by_distance[:limit], "cheapest": by_price[:limit]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_FIND_CLOSEST,
        find_closest_stations,
        schema=SERVICE_FIND_CLOSEST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    _LOGGER.debug("Registered %s.%s service", DOMAIN, SERVICE_FIND_CLOSEST)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries to the new version."""
    _LOGGER.debug("Migrating from version %s to 5", config_entry.version)
    
    if config_entry.version < 5:
        hass.config_entries.async_update_entry(config_entry, version=5)
        
    _LOGGER.debug("Migration to version 5 successful")
    return True
