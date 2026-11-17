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


# Below this speed (m/s, ~7 km/h) a GPS course is noise.
MIN_MOVING_SPEED = 2.0
# Minimum displacement between two fixes to trust the bearing between them.
MIN_MOVEMENT_KM = 0.2


def resolve_heading(
    lat: float,
    lon: float,
    course: float | None,
    speed: float | None,
    from_lat: float | None = None,
    from_lon: float | None = None,
) -> tuple[float | None, str | None, str | None]:
    """Pick the direction of travel.

    Returns (heading, source, reason): source is "gps" or "movement"; when no
    heading can be trusted, heading/source are None and reason says why
    ("stopped" or "no_heading").
    """
    moving = speed is None or speed >= MIN_MOVING_SPEED
    # Android reports course 0 when it has no bearing, so 0 is only trusted with a real speed.
    gps_ok = course is not None and moving and (course != 0 or (speed or 0) >= MIN_MOVING_SPEED)

    if gps_ok and course != 0:
        return float(course) % 360, "gps", None

    if from_lat is not None and from_lon is not None:
        if haversine_km(from_lat, from_lon, lat, lon) >= MIN_MOVEMENT_KM:
            return bearing_deg(from_lat, from_lon, lat, lon), "movement", None

    if gps_ok:  # course exactly 0 while clearly moving: driving due north
        return 0.0, "gps", None

    if speed is not None and speed < MIN_MOVING_SPEED:
        return None, None, "stopped"
    return None, None, "no_heading"


# ----------------------------------------------------------------------
# Along a route
# ----------------------------------------------------------------------
KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQUATOR = 111.320


def simplify_route(points: list[tuple[float, float]], min_step_km: float = 0.1) -> list[tuple[float, float]]:
    """Drop route points closer than min_step_km to the previous kept one (keeps the last point)."""
    if len(points) < 3:
        return list(points)
    kept = [points[0]]
    for point in points[1:-1]:
        if haversine_km(kept[-1][0], kept[-1][1], point[0], point[1]) >= min_step_km:
            kept.append(point)
    kept.append(points[-1])
    return kept


def _project_on_segment(
    lat: float, lon: float, a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float]:
    """(distance km from point to segment a-b, fraction 0..1 along the segment).

    Local flat projection around the point: accurate to well under 1 % over a few km.
    """
    kx = KM_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat))
    ax, ay = (a[1] - lon) * kx, (a[0] - lat) * KM_PER_DEG_LAT
    bx, by = (b[1] - lon) * kx, (b[0] - lat) * KM_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(px, py), t


def stations_along_route(
    stations: list[dict[str, Any]],
    route: list[tuple[float, float]],
    max_offset_km: float,
    fuel_id: str,
    fill_liters: float = 40.0,
    consumption_l_100km: float = 9.0,
) -> list[dict[str, Any]]:
    """Stations within max_offset_km of a route given as [(lat, lon), ...].

    Each result gets:
      route_km        how far along the route the closest point is
      offset_km       straight-line distance from the route
      detour_km       rough extra driving (there and back: 2 x offset)
      effective_price price per litre once the detour's fuel is counted
    """
    route = simplify_route(route)
    if len(route) < 2:
        return []

    # Cumulative distance at each route point.
    cumulative = [0.0]
    for a, b in zip(route, route[1:]):
        cumulative.append(cumulative[-1] + haversine_km(a[0], a[1], b[0], b[1]))

    # Grid index of segments so each station only checks nearby ones.
    cell_deg = max(max_offset_km, 1.0) / KM_PER_DEG_LAT
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (a, b) in enumerate(zip(route, route[1:])):
        lat_lo, lat_hi = sorted((a[0], b[0]))
        lon_lo, lon_hi = sorted((a[1], b[1]))
        for gy in range(math.floor(lat_lo / cell_deg), math.floor(lat_hi / cell_deg) + 1):
            for gx in range(math.floor(lon_lo / cell_deg), math.floor(lon_hi / cell_deg) + 1):
                grid.setdefault((gy, gx), []).append(i)

    # Longitude cells are narrower in km than latitude cells, so look further sideways.
    lat_mid = route[len(route) // 2][0]
    lon_reach = math.ceil(1 / max(math.cos(math.radians(lat_mid)), 0.1))

    lats = [p[0] for p in route]
    lons = [p[1] for p in route]
    margin = 2 * cell_deg * lon_reach
    min_lat, max_lat = min(lats) - margin, max(lats) + margin
    min_lon, max_lon = min(lons) - margin, max(lons) + margin

    results: list[dict[str, Any]] = []
    for station in stations:
        s_lat, s_lon = station.get("latitude"), station.get("longitude")
        if not s_lat or not s_lon:
            continue
        if not (min_lat <= s_lat <= max_lat and min_lon <= s_lon <= max_lon):
            continue

        gy, gx = math.floor(s_lat / cell_deg), math.floor(s_lon / cell_deg)
        segments: set[int] = set()
        for dy in (-1, 0, 1):
            for dx in range(-lon_reach - 1, lon_reach + 2):
                segments.update(grid.get((gy + dy, gx + dx), ()))
        if not segments:
            continue

        best: tuple[float, float] | None = None  # (offset, route_km)
        for i in segments:
            dist, t = _project_on_segment(s_lat, s_lon, route[i], route[i + 1])
            if best is None or dist < best[0]:
                best = (dist, cumulative[i] + t * (cumulative[i + 1] - cumulative[i]))
        if best is None or best[0] > max_offset_km:
            continue

        item = find_price_item(station, fuel_id)
        if item is None or item.get("IsAvailable") is False:
            continue
        price = parse_price(item.get("Price"))
        if price is None:
            continue

        offset, route_km = best
        detour = 2 * offset
        extra_litres = detour * consumption_l_100km / 100
        effective = price * (1 + extra_litres / fill_liters) if fill_liters > 0 else price

        result = dict(station)
        result["target_price"] = price
        result["route_km"] = round(route_km, 1)
        result["offset_km"] = round(offset, 2)
        result["detour_km"] = round(detour, 1)
        result["effective_price"] = round(effective, 1)
        results.append(result)
    return results
