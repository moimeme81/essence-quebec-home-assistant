"""find_stations_along_route: place resolution, route matching, errors."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.regie_essence_quebec.const import DOMAIN
from custom_components.regie_essence_quebec.helpers import stations_along_route
from custom_components.regie_essence_quebec.routing import (
    GeocodingError,
    RoutingError,
    parse_latlon,
)

from .conftest import ADDR_A, ADDR_B, ADDR_C, default_stations
from .test_init import _entry, _setup

ROUTE_CLIENT = "custom_components.regie_essence_quebec.routing.RouteClient"

# Straight road east along latitude 46.80, through station A; B is ~1.1 km north of it.
ROUTE_POINTS = [(46.80, -71.40 + i * 0.01) for i in range(31)]  # -71.40 -> -71.10, ~23 km
ROUTE = {"distance_km": 23.0, "duration_min": 18, "points": ROUTE_POINTS}


def test_parse_latlon():
    assert parse_latlon("46.81, -71.21") == (46.81, -71.21)
    assert parse_latlon("46.81;-71.21") == (46.81, -71.21)
    assert parse_latlon("Sherbrooke") is None
    assert parse_latlon("200, 10") is None


def test_stations_along_route_math():
    res = {s["Address"]: s for s in stations_along_route(default_stations(), ROUTE_POINTS, 2, "regular")}
    assert set(res) == {ADDR_A, ADDR_B}
    assert res[ADDR_A]["offset_km"] == 0.0
    assert 15 < res[ADDR_A]["route_km"] < 16
    assert 1.0 < res[ADDR_B]["offset_km"] < 1.2
    assert res[ADDR_B]["effective_price"] > res[ADDR_B]["target_price"]
    # Tighter corridor drops B.
    res = stations_along_route(default_stations(), ROUTE_POINTS, 0.5, "regular")
    assert [s["Address"] for s in res] == [ADDR_A]


def test_route_crossing_many_cells_and_curves():
    # An L-shaped route: north then east. A station near the corner must be found once.
    route = [(46.0 + i * 0.01, -72.0) for i in range(51)] + [(46.5, -72.0 + i * 0.01) for i in range(1, 51)]
    station = {
        "Address": "corner", "latitude": 46.505, "longitude": -71.995,
        "Prices": [{"GasType": "Régulier", "Price": "150¢", "IsAvailable": True}],
    }
    res = stations_along_route([station], route, 1, "regular")
    assert len(res) == 1
    assert 55 < res[0]["route_km"] < 57


@pytest.fixture
def route_client():
    with patch(f"{ROUTE_CLIENT}.async_route", new=AsyncMock(return_value=ROUTE)) as route, patch(
        f"{ROUTE_CLIENT}.async_geocode",
        new=AsyncMock(return_value={"latitude": 46.80, "longitude": -71.10, "label": "Quelque part, Québec"}),
    ) as geocode:
        yield {"route": route, "geocode": geocode}


async def _call(hass: HomeAssistant, **data):
    return await hass.services.async_call(
        DOMAIN, "find_stations_along_route", data, blocking=True, return_response=True
    )


async def test_along_route_with_coordinates(hass: HomeAssistant, feed, route_client) -> None:
    await _setup(hass, _entry(ADDR_A))
    result = await _call(hass, origin="46.80,-71.40", destination="46.80,-71.10")

    assert result["route"] == {"distance_km": 23.0, "duration_min": 18}
    assert result["count"] == 2
    assert [s["Address"] for s in result["along"]] == [ADDR_B, ADDR_A] or [
        s["Address"] for s in result["along"]
    ] == [ADDR_A, ADDR_B]
    assert result["cheapest"][0]["Address"] == ADDR_B  # Costco 165.9 vs 170.9
    assert ADDR_C not in [s["Address"] for s in result["along"]]
    route_client["geocode"].assert_not_called()
    origin, destination = route_client["route"].call_args.args[:2]
    assert origin == (46.80, -71.40) and destination == (46.80, -71.10)


async def test_places_from_entities_zones_and_addresses(hass: HomeAssistant, feed, route_client) -> None:
    await _setup(hass, _entry(ADDR_A))
    hass.states.async_set("device_tracker.phone", "not_home", {"latitude": 46.80, "longitude": -71.40})
    hass.states.async_set(
        "zone.travail", "0", {"latitude": 46.80, "longitude": -71.10, "friendly_name": "Travail"}
    )

    result = await _call(hass, origin="device_tracker.phone", destination="Travail")
    assert result["origin"]["source"] == "entity"
    assert result["destination"]["source"] == "zone"
    assert result["destination"]["label"] == "Travail"

    result = await _call(hass, origin="device_tracker.phone", destination="1 rue Quelconque, Québec")
    assert result["destination"]["source"] == "address"
    route_client["geocode"].assert_awaited_once_with("1 rue Quelconque, Québec")

    # Default origin is Home: Home Assistant's own location when zone.home is not loaded...
    result = await _call(hass, destination="Travail")
    assert result["origin"]["source"] == "home"
    assert result["origin"]["latitude"] == hass.config.latitude
    # ...or the zone.home entity when it is.
    hass.states.async_set("zone.home", "0", {"latitude": 46.0, "longitude": -72.0, "friendly_name": "Maison"})
    result = await _call(hass, destination="Travail")
    assert result["origin"]["source"] == "entity" and result["origin"]["latitude"] == 46.0
    result = await _call(hass, origin="maison", destination="Travail")
    assert result["origin"]["source"] == "zone"

    # Something that looks like an entity but doesn't exist is an error, never an address lookup.
    route_client["geocode"].reset_mock()
    with pytest.raises(ServiceValidationError, match="Entity not found"):
        await _call(hass, origin="device_tracker.oops", destination="Travail")
    route_client["geocode"].assert_not_called()


async def test_start_after_km_and_limits(hass: HomeAssistant, feed, route_client) -> None:
    await _setup(hass, _entry(ADDR_A))
    result = await _call(hass, origin="46.80,-71.40", destination="46.80,-71.10", start_after_km=20)
    assert result["count"] == 0

    result = await _call(
        hass, origin="46.80,-71.40", destination="46.80,-71.10", exclude_brands=["costco"], limit=1
    )
    assert [s["Address"] for s in result["along"]] == [ADDR_A]


async def test_errors(hass: HomeAssistant, feed, route_client) -> None:
    await _setup(hass, _entry(ADDR_A))

    route_client["geocode"].side_effect = GeocodingError("Address not found: nulle part")
    with pytest.raises(ServiceValidationError, match="not found"):
        await _call(hass, origin="46.80,-71.40", destination="nulle part")

    route_client["route"].side_effect = RoutingError("No route found")
    with pytest.raises(HomeAssistantError, match="No route"):
        await _call(hass, origin="46.80,-71.40", destination="46.80,-71.10")

    hass.states.async_set("sensor.nothing", "1")
    with pytest.raises(ServiceValidationError, match="no location"):
        await _call(hass, origin="46.80,-71.40", destination="sensor.nothing")
