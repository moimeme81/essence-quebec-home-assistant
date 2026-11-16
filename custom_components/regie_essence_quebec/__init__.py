"""The Régie Essence Québec integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
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
from .helpers import normalize_fuel, search_stations

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

DATA_LOCK = "lock"

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

    async def find_closest_stations(call: ServiceCall) -> ServiceResponse:
        fuel_id = normalize_fuel(call.data["gas_type"])
        if fuel_id is None:
            raise ServiceValidationError(
                f"Unknown gas type '{call.data['gas_type']}'. Use Régulier, Super or Diesel."
            )

        coordinator: RegieEssenceCoordinator | None = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
        if coordinator is None:
            raise ServiceValidationError(
                "Add at least one station to the Régie Essence Québec integration first."
            )
        if coordinator.data is None:
            await coordinator.async_refresh()
        if not coordinator.data:
            raise HomeAssistantError("No station data available from the Régie yet.")

        limit: int = call.data["limit"]
        valid = search_stations(
            list(coordinator.data.values()),
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
