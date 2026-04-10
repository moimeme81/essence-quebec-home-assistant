"""API client for Régie Essence Québec (Direct Connection)."""
import logging
import gzip
import json
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Direct link to the government data
GEOJSON_URL = "https://regieessencequebec.ca/stations.geojson.gz"

class RegieEssenceClient:
    """Async client that communicates directly with the Régie server."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _fetch_and_parse(self) -> list[dict[str, Any]]:
        # Spoof a real browser so the government firewall doesn't block Home Assistant
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            async with self._session.get(GEOJSON_URL, headers=headers) as response:
                response.raise_for_status()
                content = await response.read()
                
                try:
                    # Decompress the .gz file in memory
                    json_text = gzip.decompress(content).decode('utf-8')
                except OSError:
                    # Fallback just in case they stop zipping the file
                    json_text = content.decode('utf-8')
                    
                data = json.loads(json_text)
                features = data.get("features", [])
                
                stations = []
                for feature in features:
                    props = feature.get("properties", {})
                    coords = feature.get("geometry", {}).get("coordinates", [0, 0])
                    
                    stations.append({
                        "Name": props.get("Name", ""),
                        "brand": props.get("brand", ""),
                        "Address": props.get("Address", ""),
                        "Region": props.get("Region", ""),
                        "latitude": coords[1] if len(coords) > 1 else 0,
                        "longitude": coords[0] if len(coords) > 0 else 0,
                        # Pass the Prices list natively without stringifying it!
                        "Prices": props.get("Prices", [])
                    })
                return stations
                
        except Exception as err:
            _LOGGER.error("Error fetching data directly from Régie: %s", err)
            raise

    async def async_get_all_stations(self) -> list[dict[str, Any]]:
        """Fetch all stations for the setup dropdowns."""
        return await self._fetch_and_parse()

    async def async_get_station(
        self, address: str, lat: float | None = None, lon: float | None = None
    ) -> dict[str, Any] | None:
        """Fetch all stations and filter down to the specific one being monitored."""
        stations = await self._fetch_and_parse()
        for station in stations:
            # Match the station by exact address
            if station.get("Address") == address:
                return station
        return None
