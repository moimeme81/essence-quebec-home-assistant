"""Shared fixtures."""
from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

CLIENT = "custom_components.regie_essence_quebec.api_client.RegieEssenceClient.async_get_all_stations"

ADDR_A = "230 av. Murdoch, Rouyn-Noranda"
ADDR_B = "1 rue Principale, Québec"
ADDR_C = "99 boul. Loin, Gaspé"


def make_station(address, lat, lon, regular, brand="Shell", diesel="189.9¢"):
    return {
        "Name": f"Station {address}",
        "brand": brand,
        "Status": "En opération",
        "Address": address,
        "PostalCode": "",
        "Region": "Test",
        "latitude": lat,
        "longitude": lon,
        "Prices": [
            {"GasType": "Régulier", "Price": regular, "IsAvailable": regular is not None},
            {"GasType": "Super", "Price": "199.9¢", "IsAvailable": True},
            {"GasType": "Diesel", "Price": diesel, "IsAvailable": diesel is not None},
        ],
    }


def default_stations() -> list[dict[str, Any]]:
    return [
        make_station(ADDR_A, 46.80, -71.20, "170.9¢"),
        make_station(ADDR_B, 46.81, -71.21, "165.9¢", brand="Costco"),
        make_station(ADDR_C, 48.83, -64.48, "160.0¢"),
    ]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def feed():
    """Mutable feed returned by the mocked client; tests can edit it between refreshes."""
    state = {"stations": default_stations()}

    async def _fetch(self):
        return copy.deepcopy(state["stations"])

    with patch(CLIENT, autospec=True, side_effect=_fetch) as mock:
        state["mock"] = mock
        yield state
