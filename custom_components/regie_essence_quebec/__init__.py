"""Régie Essence Québec integration."""
from __future__ import annotations

import logging
import math

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import DOMAIN
from .coordinator import RegieEssenceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Régie Essence Québec from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = RegieEssenceCoordinator(hass, entry.data, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Register the custom service to find closest stations (only register once)
    if not hass.services.has_service(DOMAIN, "find_closest_stations"):
        async def find_closest_stations(call: ServiceCall) -> dict:
            lat = float(call.data.get("latitude", 0))
            lon = float(call.data.get("longitude", 0))
            limit = int(call.data.get("limit", 5))

            if lat == 0 or lon == 0:
                raise ValueError("Valid latitude and longitude must be provided.")

            # Grab the client from the coordinator
            client = coordinator._client
            stations = await client.async_get_all_stations()

            # Calculate distance using the Haversine formula
            for s in stations:
                s_lat = s.get("latitude", 0)
                s_lon = s.get("longitude", 0)
                if s_lat and s_lon:
                    R = 6371.0 # Earth radius in km
                    dlat = math.radians(s_lat - lat)
                    dlon = math.radians(s_lon - lon)
                    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(s_lat)) * math.sin(dlon / 2)**2
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    s["distance_km"] = round(R * c, 2)
                else:
                    s["distance_km"] = 99999

            # Sort by distance and grab the top X
            stations.sort(key=lambda x: x.get("distance_km", 99999))
            closest = stations[:limit]

            return {"stations": closest}

        hass.services.async_register(
            DOMAIN, "find_closest_stations", find_closest_stations,
            supports_response=SupportsResponse.ONLY
        )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
