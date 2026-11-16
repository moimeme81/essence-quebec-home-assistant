"""Integration tests: shared coordinator, trends, service, config flow and migration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.regie_essence_quebec.const import DATA_COORDINATOR, DOMAIN

from .conftest import ADDR_A, ADDR_B, ADDR_C


def _entry(address: str, **kwargs) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=kwargs.pop("version", 6),
        unique_id=kwargs.pop("unique_id", address),
        title=address,
        data={"address": address, "scan_interval": kwargs.pop("scan_interval", 60)},
        **kwargs,
    )


def _state(hass: HomeAssistant, entry: MockConfigEntry, unique_suffix: str):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{unique_suffix}"
    )
    assert entity_id, unique_suffix
    return hass.states.get(entity_id)


async def _setup(hass: HomeAssistant, *entries: MockConfigEntry) -> None:
    for entry in entries:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entries[0].entry_id)
    await hass.async_block_till_done()


async def test_one_download_for_many_stations(hass: HomeAssistant, feed) -> None:
    a, b = _entry(ADDR_A), _entry(ADDR_B)
    await _setup(hass, a, b)

    assert a.state is ConfigEntryState.LOADED
    assert b.state is ConfigEntryState.LOADED
    assert feed["mock"].call_count == 1

    assert float(_state(hass, a, "regular").state) == 170.9
    assert float(_state(hass, b, "regular").state) == 165.9
    assert _state(hass, a, "regular_trend").state == "stable"


async def test_trends_tracked_for_every_station(hass: HomeAssistant, feed) -> None:
    a, b = _entry(ADDR_A), _entry(ADDR_B)
    await _setup(hass, a, b)
    coordinator = hass.data[DOMAIN][DATA_COORDINATOR]

    feed["stations"][0]["Prices"][0]["Price"] = "175.9¢"  # A goes up
    feed["stations"][1]["Prices"][0]["Price"] = "160.9¢"  # B goes down
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _state(hass, a, "regular_trend").state == "up"
    assert _state(hass, b, "regular_trend").state == "down"

    # A missing price must not be recorded as 0 (which used to produce a fake "up" next time).
    feed["stations"][0]["Prices"][0]["Price"] = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, a, "regular").state == "unknown"
    assert _state(hass, a, "regular_trend").state == "up"

    feed["stations"][0]["Prices"][0]["Price"] = "175.9¢"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, a, "regular_trend").state == "up"
    assert coordinator._memory[ADDR_A]["Régulier"]["price"] == 175.9
    assert coordinator._memory[ADDR_B]["Régulier"]["price"] == 160.9


async def test_interval_uses_shortest_and_unload(hass: HomeAssistant, feed) -> None:
    a = _entry(ADDR_A, scan_interval=60)
    b = _entry(ADDR_B, scan_interval=5)  # below minimum -> clamped to 15
    await _setup(hass, a, b)
    coordinator = hass.data[DOMAIN][DATA_COORDINATOR]
    assert coordinator.update_interval == timedelta(minutes=15)

    assert await hass.config_entries.async_unload(b.entry_id)
    assert coordinator.update_interval == timedelta(minutes=60)
    assert await hass.config_entries.async_unload(a.entry_id)
    assert DATA_COORDINATOR not in hass.data[DOMAIN]


async def test_setup_retries_when_feed_down(hass: HomeAssistant, feed) -> None:
    feed["mock"].side_effect = OSError("boom")
    a = _entry(ADDR_A)
    a.add_to_hass(hass)
    await hass.config_entries.async_setup(a.entry_id)
    await hass.async_block_till_done()
    assert a.state is ConfigEntryState.SETUP_RETRY


async def test_find_closest_service(hass: HomeAssistant, feed) -> None:
    await _setup(hass, _entry(ADDR_A))
    result = await hass.services.async_call(
        DOMAIN,
        "find_closest_stations",
        {"latitude": 46.80, "longitude": -71.20, "radius": 10, "gas_type": "Ordinaire", "limit": 3},
        blocking=True,
        return_response=True,
    )
    assert [s["Address"] for s in result["closest"]] == [ADDR_A, ADDR_B]
    assert [s["Address"] for s in result["cheapest"]] == [ADDR_B, ADDR_A]
    assert ADDR_C not in [s["Address"] for s in result["closest"]]
    # The service uses the coordinator's data instead of downloading again.
    assert feed["mock"].call_count == 1


async def test_migration_from_v5(hass: HomeAssistant, feed) -> None:
    old = _entry(ADDR_A, version=5, unique_id=None, scan_interval=5)
    dup = _entry(ADDR_A, version=5, unique_id=None, scan_interval=5)
    await _setup(hass, old, dup)

    assert old.version == 6 and dup.version == 6
    assert old.data["scan_interval"] == 60
    # Only one of the duplicates can own the unique id.
    assert sorted([old.unique_id or "", dup.unique_id or ""]) == ["", ADDR_A]


async def test_config_flow_hides_and_rejects_configured(hass: HomeAssistant, feed) -> None:
    await _setup(hass, _entry(ADDR_A))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "search"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"search_region": "test"})
    assert result["step_id"] == "select_stations"
    options = result["data_schema"].schema["selected_stations"].config["options"]
    values = [o["value"] for o in options]
    assert ADDR_A not in values and ADDR_B in values

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"selected_stations": [ADDR_B, ADDR_C]}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    addresses = sorted(e.data["address"] for e in hass.config_entries.async_entries(DOMAIN))
    assert addresses == sorted([ADDR_A, ADDR_B, ADDR_C])

    # A duplicate import is rejected.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={"address": ADDR_B, "title": "x"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
