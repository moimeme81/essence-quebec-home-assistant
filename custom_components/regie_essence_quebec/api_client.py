"""API client for Régie Essence Québec (direct connection to the public feed)."""
from __future__ import annotations

import gzip
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

GEOJSON_URL = "https://regieessencequebec.ca/stations.geojson.gz"
USER_AGENT = "HomeAssistant-RegieEssenceQuebec (+https://github.com/moimeme81/essence-quebec-home-assistant)"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class RegieEssenceClient:
    """Async client that downloads and parses the province-wide station file."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def async_get_all_stations(self) -> list[dict[str, Any]]:
        """Fetch every station in Québec."""
        try:
            async with self._session.get(
                GEOJSON_URL, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                content = await response.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Error fetching data from Régie: %s", err)
            raise

        try:
            json_text = gzip.decompress(content).decode("utf-8")
        except OSError:
            # Some proxies/servers transparently decompress already.
            json_text = content.decode("utf-8")

        data = json.loads(json_text)
        stations: list[dict[str, Any]] = []
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or [0, 0]
            stations.append(
                {
                    "Name": props.get("Name", ""),
                    "brand": props.get("brand", ""),
                    "Status": props.get("Status", ""),
                    "Address": props.get("Address", ""),
                    "PostalCode": props.get("PostalCode", ""),
                    "Region": props.get("Region", ""),
                    "latitude": coords[1] if len(coords) > 1 else 0,
                    "longitude": coords[0] if len(coords) > 0 else 0,
                    "Prices": props.get("Prices") or [],
                }
            )
        return stations
