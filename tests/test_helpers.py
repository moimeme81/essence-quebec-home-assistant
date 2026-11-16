"""Unit tests for pure helpers."""
from custom_components.regie_essence_quebec.helpers import (
    compute_trend,
    find_price_item,
    get_city,
    haversine_km,
    normalize_fuel,
    parse_price,
    search_stations,
)

from .conftest import ADDR_A, default_stations


def test_parse_price():
    assert parse_price("186.9¢") == 186.9
    assert parse_price("186,9 ¢") == 186.9
    assert parse_price(175) == 175.0
    assert parse_price(None) is None
    assert parse_price("N/D") is None
    assert parse_price("") is None
    assert parse_price("0¢") is None


def test_normalize_fuel():
    assert normalize_fuel("Régulier") == "regular"
    assert normalize_fuel(" ordinaire ") == "regular"
    assert normalize_fuel("Diésel") == "diesel"
    assert normalize_fuel("Premium") == "super"
    assert normalize_fuel("super") == "super"
    assert normalize_fuel("kerosene") is None
    assert normalize_fuel(None) is None


def test_compute_trend():
    assert compute_trend(None, None, 170.0) == "stable"
    assert compute_trend(170.0, "stable", 171.0) == "up"
    assert compute_trend(171.0, "up", 169.0) == "down"
    # Unchanged price keeps the last direction.
    assert compute_trend(169.0, "down", 169.0) == "down"


def test_get_city():
    assert get_city(ADDR_A) == "Rouyn-Noranda"
    assert get_city("") == "Inconnu"
    assert get_city("Sans virgule") == "Sans virgule"


def test_haversine():
    # Montréal -> Québec is ~233 km as the crow flies.
    assert 225 < haversine_km(45.5017, -73.5673, 46.8139, -71.2080) < 240


def test_search_stations_filters_radius_and_missing_prices():
    stations = default_stations()
    stations[1]["Prices"][0]["Price"] = None  # station B has no regular price
    results = search_stations(stations, 46.80, -71.20, 10, "regular")
    assert [s["Address"] for s in results] == [ADDR_A]
    assert results[0]["target_price"] == 170.9
    assert results[0]["distance_km"] == 0.0


def test_find_price_item():
    station = default_stations()[0]
    assert find_price_item(station, "diesel")["Price"] == "189.9¢"
    assert find_price_item(None, "diesel") is None
