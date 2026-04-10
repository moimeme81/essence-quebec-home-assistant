"""DataUpdateCoordinator for Régie Essence Québec."""
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_ADDRESS, CONF_LATITUDE, CONF_LONGITUDE
from .api_client import RegieEssenceClient

_LOGGER = logging.getLogger(__name__)

class RegieEssenceCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        entry_data: dict[str, Any],
        config_entry: ConfigEntry = None
    ) -> None:
        self.address = entry_data.get(CONF_ADDRESS)
        self.lat = entry_data.get(CONF_LATITUDE)
        self.lon = entry_data.get(CONF_LONGITUDE)
        
        # Read from options first, fallback to original data
        scan_interval = 60
        if config_entry:
            # Safely grab the options dictionary using the correct protected variable
            scan_interval = config_entry.options.get(
                "scan_interval", 
                entry_data.get("scan_interval", 60)
            )

        session = async_get_clientsession(hass)
        self._client = RegieEssenceClient(session)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        if not self.address:
            raise UpdateFailed("No station address configured.")

        try:
            station = await self._client.async_get_station(self.address, self.lat, self.lon)
        except Exception as err:
            raise UpdateFailed(f"Network error fetching API data: {err}") from err

        if not station:
            _LOGGER.warning(f"Monitored station at '{self.address}' not found in current dataset.")

        return {
            "station": station,
            "found": station is not None,
        }
