"""The Régie Essence Québec integration."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ADDRESS,
    CONF_SCAN_INTERVAL,
    DATA_COORDINATOR,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SEARCH_RADIUS_KM,
)
from .coordinator import RegieEssenceCoordinator
from .helpers import (
    exclude_brands,
    normalize_fuel,
    resolve_heading,
    search_stations,
    stations_ahead,
    stations_along_route,
)
from .routing import DEFAULT_OSRM_URL, GeocodingError, RouteClient, RoutingError, parse_latlon

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

DATA_LOCK = "lock"
DATA_ROUTE_CLIENT = "route_client"
ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

SERVICE_FIND_CLOSEST = "find_closest_stations"
SERVICE_FIND_CLOSEST_SCHEMA = vol.Schema(
    {
        vol.Required("latitude"): cv.latitude,
        vol.Required("longitude"): cv.longitude,
        vol.Optional("limit", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
        vol.Optional("radius", default=10.0): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=MAX_SEARCH_RADIUS_KM)
        ),
        vol.Optional("gas_type", default="Régulier"): cv.string,
        vol.Optional("exclude_brands", default=[]): vol.All(cv.ensure_list, [cv.string]),
    }
)

SERVICE_FIND_AHEAD = "find_stations_ahead"
SERVICE_FIND_AHEAD_SCHEMA = vol.Schema(
    {
        vol.Required("latitude"): cv.latitude,
        vol.Required("longitude"): cv.longitude,
        # GPS course from the phone. Optional: without it (or when stopped) the direction is
        # worked out from from_latitude/from_longitude, else a radius search is done.
        vol.Optional("heading"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=360))),
        vol.Optional("speed"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0))),
        vol.Optional("from_latitude"): vol.Any(None, cv.latitude),
        vol.Optional("from_longitude"): vol.Any(None, cv.longitude),
        vol.Optional("fallback_radius", default=10.0): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=MAX_SEARCH_RADIUS_KM)
        ),
        vol.Optional("distance", default=30.0): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=MAX_SEARCH_RADIUS_KM)
        ),
        vol.Optional("max_offset", default=2.0): vol.All(
            vol.Coerce(float), vol.Range(min=0.2, max=20)
        ),
        vol.Optional("limit", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
        vol.Optional("gas_type", default="Régulier"): cv.string,
        vol.Optional("exclude_brands", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("fill_liters", default=40.0): vol.All(
            vol.Coerce(float), vol.Range(min=5, max=200)
        ),
        vol.Optional("consumption", default=9.0): vol.All(
            vol.Coerce(float), vol.Range(min=2, max=40)
        ),
    }
)


SERVICE_FIND_ALONG_ROUTE = "find_stations_along_route"
SERVICE_FIND_ALONG_ROUTE_SCHEMA = vol.Schema(
    {
        # Each accepts: "lat,lon", an entity (zone./person./device_tracker.), a zone name
        # ("Travail"), or an address ("1 rue Principale, Sherbrooke").
        vol.Optional("origin", default="zone.home"): cv.string,
        vol.Required("destination"): cv.string,
        vol.Optional("max_offset", default=2.0): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=20)),
        vol.Optional("limit", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Optional("gas_type", default="Régulier"): cv.string,
        vol.Optional("exclude_brands", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("fill_liters", default=40.0): vol.All(vol.Coerce(float), vol.Range(min=5, max=200)),
        vol.Optional("consumption", default=9.0): vol.All(vol.Coerce(float), vol.Range(min=2, max=40)),
        vol.Optional("start_after_km", default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("routing_url", default=DEFAULT_OSRM_URL): cv.url,
    }
)


def _domain_data(hass: HomeAssistant) -> dict[str, Any]:
    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault(DATA_LOCK, asyncio.Lock())
    return data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (services are global, registered once)."""
    _domain_data(hass)
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one monitored station, sharing the province-wide coordinator."""
    domain_data = _domain_data(hass)

    async with domain_data[DATA_LOCK]:
        coordinator: RegieEssenceCoordinator | None = domain_data.get(DATA_COORDINATOR)
        if coordinator is None:
            coordinator = RegieEssenceCoordinator(hass)
            domain_data[DATA_COORDINATOR] = coordinator

        coordinator.register_entry(entry)

        if coordinator.data is None:
            await coordinator.async_refresh()
            if not coordinator.last_update_success:
                coordinator.unregister_entry(entry.entry_id)
                raise ConfigEntryNotReady("Could not download Régie Essence Québec data")
        else:
            await coordinator.async_apply_trends_for(entry.data.get(CONF_ADDRESS, ""))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = _domain_data(hass)
        coordinator: RegieEssenceCoordinator | None = domain_data.get(DATA_COORDINATOR)
        if coordinator is not None:
            coordinator.unregister_entry(entry.entry_id)
            if not coordinator.has_entries:
                domain_data.pop(DATA_COORDINATOR, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_FIND_CLOSEST):
        return

    def _fuel(call: ServiceCall) -> str:
        fuel_id = normalize_fuel(call.data["gas_type"])
        if fuel_id is None:
            raise ServiceValidationError(
                f"Unknown gas type '{call.data['gas_type']}'. Use Régulier, Super or Diesel."
            )
        return fuel_id

    async def _stations(call: ServiceCall) -> list[dict[str, Any]]:
        coordinator: RegieEssenceCoordinator | None = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
        if coordinator is None:
            raise ServiceValidationError(
                "Add at least one station to the Régie Essence Québec integration first."
            )
        if coordinator.data is None:
            await coordinator.async_refresh()
        if not coordinator.data:
            raise HomeAssistantError("No station data available from the Régie yet.")
        return exclude_brands(list(coordinator.data.values()), call.data["exclude_brands"])

    async def find_closest_stations(call: ServiceCall) -> ServiceResponse:
        fuel_id = _fuel(call)
        limit: int = call.data["limit"]
        valid = search_stations(
            await _stations(call),
            call.data["latitude"],
            call.data["longitude"],
            call.data["radius"],
            fuel_id,
        )

        by_distance = sorted(valid, key=lambda s: s["distance_km"])
        by_price = sorted(valid, key=lambda s: (s["target_price"], s["distance_km"]))
        return {"closest": by_distance[:limit], "cheapest": by_price[:limit]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_FIND_CLOSEST,
        find_closest_stations,
        schema=SERVICE_FIND_CLOSEST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def find_stations_ahead(call: ServiceCall) -> ServiceResponse:
        """Stations in front of you, for use while driving (heading from the phone's GPS)."""
        fuel_id = _fuel(call)
        limit: int = call.data["limit"]
        lat, lon = call.data["latitude"], call.data["longitude"]
        speed = call.data.get("speed")
        heading, source, reason = resolve_heading(
            lat,
            lon,
            call.data.get("heading"),
            speed,
            call.data.get("from_latitude"),
            call.data.get("from_longitude"),
        )
        info: dict[str, Any] = {
            "direction_known": heading is not None,
            "heading": round(heading) if heading is not None else None,
            "heading_source": source,
            "reason": reason,
            "speed_kmh": round(speed * 3.6) if speed is not None else None,
        }
        stations = await _stations(call)

        if heading is None:
            # No usable direction: plain radius search so the driver still gets an answer.
            valid = search_stations(stations, lat, lon, call.data["fallback_radius"], fuel_id)
            by_distance = sorted(valid, key=lambda s: s["distance_km"])
            by_price = sorted(valid, key=lambda s: (s["target_price"], s["distance_km"]))
            return {
                **info,
                "next": by_distance[:limit],
                "cheapest": by_price[:limit],
                "best_value": by_price[:limit],
            }

        valid = stations_ahead(
            stations,
            lat,
            lon,
            heading,
            call.data["distance"],
            call.data["max_offset"],
            fuel_id,
            call.data["fill_liters"],
            call.data["consumption"],
        )
        by_ahead = sorted(valid, key=lambda s: s["ahead_km"])
        by_price = sorted(valid, key=lambda s: (s["target_price"], s["ahead_km"]))
        by_value = sorted(valid, key=lambda s: (s["effective_price"], s["ahead_km"]))
        return {
            **info,
            "next": by_ahead[:limit],
            "cheapest": by_price[:limit],
            "best_value": by_value[:limit],
        }

    async def find_stations_along_route(call: ServiceCall) -> ServiceResponse:
        """Stations along the driving route between two places."""
        fuel_id = _fuel(call)
        limit: int = call.data["limit"]
        origin = await _async_resolve_place(hass, call.data["origin"])
        destination = await _async_resolve_place(hass, call.data["destination"])

        try:
            route = await _route_client(hass).async_route(
                (origin["latitude"], origin["longitude"]),
                (destination["latitude"], destination["longitude"]),
                call.data["routing_url"],
            )
        except RoutingError as err:
            raise HomeAssistantError(str(err)) from err

        stations = await _stations(call)
        valid = await hass.async_add_executor_job(
            stations_along_route,
            stations,
            route["points"],
            call.data["max_offset"],
            fuel_id,
            call.data["fill_liters"],
            call.data["consumption"],
        )
        valid = [s for s in valid if s["route_km"] >= call.data["start_after_km"]]
        by_route = sorted(valid, key=lambda s: s["route_km"])
        by_price = sorted(valid, key=lambda s: (s["target_price"], s["route_km"]))
        by_value = sorted(valid, key=lambda s: (s["effective_price"], s["route_km"]))
        return {
            "origin": origin,
            "destination": destination,
            "route": {"distance_km": route["distance_km"], "duration_min": route["duration_min"]},
            "count": len(valid),
            "along": by_route[:limit],
            "cheapest": by_price[:limit],
            "best_value": by_value[:limit],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_FIND_ALONG_ROUTE,
        find_stations_along_route,
        schema=SERVICE_FIND_ALONG_ROUTE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FIND_AHEAD,
        find_stations_ahead,
        schema=SERVICE_FIND_AHEAD_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _route_client(hass: HomeAssistant) -> RouteClient:
    data = _domain_data(hass)
    if DATA_ROUTE_CLIENT not in data:
        data[DATA_ROUTE_CLIENT] = RouteClient(async_get_clientsession(hass))
    return data[DATA_ROUTE_CLIENT]


async def _async_resolve_place(hass: HomeAssistant, value: str) -> dict[str, Any]:
    """Turn coordinates / an entity / a zone name / an address into a location."""
    text = value.strip()
    if not text:
        raise ServiceValidationError("Empty origin or destination.")

    if (coords := parse_latlon(text)) is not None:
        return {"latitude": coords[0], "longitude": coords[1], "label": text, "source": "coordinates"}

    def _from_state(state) -> dict[str, Any] | None:
        lat, lon = state.attributes.get("latitude"), state.attributes.get("longitude")
        if lat is None or lon is None:
            return None
        return {
            "latitude": float(lat),
            "longitude": float(lon),
            "label": state.name,
            "source": "entity",
        }

    if ENTITY_ID_RE.match(text.lower()):
        state = hass.states.get(text.lower())
        if state is not None:
            if (place := _from_state(state)) is None:
                raise ServiceValidationError(f"{text} has no location.")
            return place
        if text.lower() != "zone.home":
            raise ServiceValidationError(f"Entity not found: {text}")

    if text.lower() in {"zone.home", "home", "maison", "domicile"} and not hass.states.get("zone.home"):
        return {
            "latitude": hass.config.latitude,
            "longitude": hass.config.longitude,
            "label": hass.config.location_name or "Home",
            "source": "home",
        }

    lowered = text.lower()
    for state in hass.states.async_all("zone"):
        names = {state.name.lower(), state.entity_id.split(".", 1)[1].replace("_", " ")}
        if state.entity_id == "zone.home":
            names |= {"home", "maison", "domicile"}
        if lowered in names and (place := _from_state(state)) is not None:
            return {**place, "source": "zone"}

    try:
        place = await _route_client(hass).async_geocode(text)
    except GeocodingError as err:
        raise ServiceValidationError(str(err)) from err
    return {**place, "source": "address"}


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    _LOGGER.debug("Migrating config entry from version %s", config_entry.version)

    if config_entry.version < 6:
        data = dict(config_entry.data)
        # 5 minutes was the hard-coded default (never user-chosen in the setup flow).
        if data.get(CONF_SCAN_INTERVAL) == 5:
            data[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL_MINUTES

        # Give the entry a unique id (its address) so the same station can't be added twice.
        address = data.get(CONF_ADDRESS)
        unique_id = config_entry.unique_id
        if unique_id is None and address:
            taken = any(
                other.unique_id == address
                for other in hass.config_entries.async_entries(DOMAIN)
                if other.entry_id != config_entry.entry_id
            )
            if not taken:
                unique_id = address

        hass.config_entries.async_update_entry(
            config_entry, data=data, unique_id=unique_id, version=6
        )

    _LOGGER.debug("Migration to version %s successful", config_entry.version)
    return True
