"""DataUpdateCoordinator for Régie Essence Québec."""
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .api_client import RegieEssenceClient

_LOGGER = logging.getLogger(__name__)

class RegieEssenceCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry
        session = async_get_clientsession(hass)
        self._client = RegieEssenceClient(session)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=60),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            # Fetch ALL stations once
            all_stations = await self._client.async_get_all_stations()
        except Exception as err:
            raise UpdateFailed(f"Network error fetching API data: {err}") from err

        # Map them by address so sensors can instantly find their specific data
        mapped_stations = {s.get("Address"): s for s in all_stations if s.get("Address")}
        return mapped_stations

    async def async_get_all_stations(self) -> list[dict[str, Any]]:
        """Fetch all stations from the upstream API."""
        return await self._client.async_get_all_stations()
