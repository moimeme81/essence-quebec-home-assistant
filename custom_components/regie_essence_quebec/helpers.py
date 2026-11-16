"""Pure helpers shared by the coordinator, sensors and services.

Kept free of Home Assistant imports so they are trivial to unit test.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .const import FUEL_ALIASES

_PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
EARTH_RADIUS_KM = 6371.0


def parse_price(raw: Any) -> float | None:
    """Turn '186.9¢' (or 186.9) into 186.9. Returns None when there is no price."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else None
    match = _PRICE_RE.search(str(raw))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value if value > 0 else None


def normalize_fuel(gas_type: Any) -> str | None:
    """Map any spelling of a fuel type ('Régulier', 'Diésel', 'regular'...) to its canonical id."""
    if gas_type is None:
        return None
    value = str(gas_type).strip().lower()
    for fuel_id, aliases in FUEL_ALIASES.items():
        if value == fuel_id or value in aliases:
            return fuel_id
    return None


def find_price_item(station: dict[str, Any] | None, fuel_id: str) -> dict[str, Any] | None:
    """Return the station's price block for a canonical fuel id."""
    if not station:
        return None
    for item in station.get("Prices") or []:
        if normalize_fuel(item.get("GasType")) == fuel_id:
            return item
    return None


def get_city(address: str | None) -> str:
    """Addresses look like '230 av. Murdoch, Rouyn-Noranda'; the city is the last part."""
    if not address:
        return "Inconnu"
    parts = address.split(",")
    return parts[-1].strip() if len(parts) > 1 else address.strip()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_trend(old_price: float | None, old_trend: str | None, new_price: float) -> str:
    """Trend keeps its last direction until the price moves again."""
    if old_price is None:
        return "stable"
    if new_price > old_price:
        return "up"
    if new_price < old_price:
        return "down"
    return old_trend or "stable"


def search_stations(
    stations: list[dict[str, Any]],
    lat: float,
    lon: float,
    radius_km: float,
    fuel_id: str,
) -> list[dict[str, Any]]:
    """Stations within radius that sell fuel_id, with distance_km and target_price added."""
    results: list[dict[str, Any]] = []
    for station in stations:
        s_lat = station.get("latitude")
        s_lon = station.get("longitude")
        if not s_lat or not s_lon:
            continue

        distance_km = haversine_km(lat, lon, s_lat, s_lon)
        if distance_km > radius_km:
            continue

        item = find_price_item(station, fuel_id)
        if item is None or item.get("IsAvailable") is False:
            continue
        price = parse_price(item.get("Price"))
        if price is None:
            continue

        result = dict(station)
        result["distance_km"] = round(distance_km, 2)
        result["target_price"] = price
        results.append(result)
    return results
