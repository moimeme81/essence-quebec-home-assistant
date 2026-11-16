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


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing (0 = north, 90 = east) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# How much the allowed side offset grows with distance ahead (15 % of the distance),
# so stations on a highway that curves away from the straight line are still found.
AHEAD_WIDENING = 0.15


def exclude_brands(stations: list[dict[str, Any]], brands: list[str] | None) -> list[dict[str, Any]]:
    """Drop stations whose brand contains any of the given words (case-insensitive)."""
    words = [b.strip().lower() for b in brands or [] if b and b.strip()]
    if not words:
        return stations
    return [
        s for s in stations if not any(w in str(s.get("brand") or "").lower() for w in words)
    ]


def stations_ahead(
    stations: list[dict[str, Any]],
    lat: float,
    lon: float,
    heading: float,
    distance_km: float,
    max_offset_km: float,
    fuel_id: str,
    fill_liters: float = 40.0,
    consumption_l_100km: float = 9.0,
) -> list[dict[str, Any]]:
    """Stations in front of a moving vehicle.

    Each result gets:
      ahead_km      distance along the direction of travel
      offset_km     distance to the side of that line
      detour_km     rough extra driving to reach it and come back (2 x offset, straight line)
      effective_price  price per litre once the fuel burnt on the detour is counted
    """
    candidates = search_stations(
        stations, lat, lon, distance_km + max_offset_km, fuel_id
    )
    results: list[dict[str, Any]] = []
    for station in candidates:
        dist = haversine_km(lat, lon, station["latitude"], station["longitude"])
        angle = math.radians(
            ((bearing_deg(lat, lon, station["latitude"], station["longitude"]) - heading + 540) % 360)
            - 180
        )
        ahead = dist * math.cos(angle)
        offset = abs(dist * math.sin(angle))
        if ahead <= 0 or ahead > distance_km:
            continue
        if offset > max_offset_km + ahead * AHEAD_WIDENING:
            continue

        detour = 2 * offset
        price = station["target_price"]
        extra_litres = detour * consumption_l_100km / 100
        effective = price * (1 + extra_litres / fill_liters) if fill_liters > 0 else price

        station["ahead_km"] = round(ahead, 1)
        station["offset_km"] = round(offset, 1)
        station["detour_km"] = round(detour, 1)
        station["effective_price"] = round(effective, 1)
        results.append(station)
    return results
