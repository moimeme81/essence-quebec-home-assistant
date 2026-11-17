"""Geocoding (OpenStreetMap Nominatim) and road routing (OSRM) for route searches."""
from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from .api_client import USER_AGENT

_LOGGER = logging.getLogger(__name__)

# Public demo servers: fine for personal use (a request now and then), not for heavy traffic.
# A self-hosted OSRM can be used instead through the service's routing_url field.
DEFAULT_OSRM_URL = "https://router.project-osrm.org"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT = aiohttp.ClientTimeout(total=20)

_LATLON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;]\s*(-?\d+(?:\.\d+)?)\s*$")


class RoutingError(Exception):
    """Route could not be computed."""


class GeocodingError(Exception):
    """Address could not be found."""


def parse_latlon(text: str) -> tuple[float, float] | None:
    """'46.81, -71.21' -> (46.81, -71.21). None if text is not a coordinate pair."""
    match = _LATLON_RE.match(text or "")
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


class RouteClient:
    """Small async client with an in-memory geocoding cache."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._geocode_cache: dict[str, dict[str, Any]] = {}

    async def async_geocode(self, query: str) -> dict[str, Any]:
        """Address -> {'latitude', 'longitude', 'label'} (biased to Canada)."""
        key = query.strip().lower()
        if key in self._geocode_cache:
            return self._geocode_cache[key]

        params = {"q": query, "format": "jsonv2", "limit": "1", "countrycodes": "ca"}
        try:
            async with self._session.get(
                NOMINATIM_URL,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "fr,en"},
                timeout=TIMEOUT,
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GeocodingError(f"Address lookup failed: {err}") from err

        if not data:
            raise GeocodingError(f"Address not found: {query}")
        place = {
            "latitude": float(data[0]["lat"]),
            "longitude": float(data[0]["lon"]),
            "label": data[0].get("display_name", query),
        }
        self._geocode_cache[key] = place
        return place

    async def async_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        base_url: str = DEFAULT_OSRM_URL,
    ) -> dict[str, Any]:
        """Driving route -> {'distance_km', 'duration_min', 'points': [(lat, lon), ...]}."""
        coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
        url = f"{base_url.rstrip('/')}/route/v1/driving/{coords}"
        try:
            async with self._session.get(
                url,
                params={"overview": "full", "geometries": "geojson"},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise RoutingError(f"Routing request failed: {err}") from err

        if data.get("code") != "Ok" or not data.get("routes"):
            raise RoutingError(f"No route found ({data.get('code')}: {data.get('message', '')})")
        route = data["routes"][0]
        return {
            "distance_km": round(route["distance"] / 1000, 1),
            "duration_min": round(route["duration"] / 60),
            "points": [(lat, lon) for lon, lat in route["geometry"]["coordinates"]],
        }
