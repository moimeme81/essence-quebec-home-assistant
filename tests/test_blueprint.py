"""Run the script blueprint inside Home Assistant with a fake phone."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from .conftest import ADDR_A
from .test_init import _entry, _setup

BLUEPRINT = Path(__file__).parent.parent / "blueprint" / "script" / "find_gas.yaml"


@pytest.fixture
async def notify_calls(hass: HomeAssistant, feed):
    await _setup(hass, _entry(ADDR_A))
    dest = Path(hass.config.path("blueprints/script/regie/find_gas.yaml"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, dest)
    return async_mock_service(hass, "notify", "mobile_app_phone")


async def _make_script(hass: HomeAssistant, **inputs) -> None:
    base = {
        "location_entity": "device_tracker.phone",
        "notify_phone": "device_tracker.phone",
        "search_mode": "ahead_best",
        "device_os": "ios",
        "nav_app": "waze",
    }
    base.update(inputs)
    assert await async_setup_component(
        hass,
        "script",
        {"script": {"gas": {"use_blueprint": {"path": "regie/find_gas.yaml", "input": base}}}},
    )
    await hass.async_block_till_done()


def _phone(hass: HomeAssistant, course=90, speed=25.0) -> None:
    hass.states.async_set(
        "device_tracker.phone",
        "not_home",
        {"latitude": 46.80, "longitude": -71.40, "course": course, "speed": speed},
    )


async def test_ahead_best_ios(hass: HomeAssistant, notify_calls) -> None:
    _phone(hass)
    await _make_script(hass)
    await hass.services.async_call("script", "gas", blocking=True)

    assert len(notify_calls) == 1
    data = notify_calls[0].data
    assert data["title"].strip() == "Meilleure valeur devant"
    assert "Costco (Québec) dans" in data["message"]
    assert "¢/L" in data["message"]
    actions = data["data"]["actions"]
    assert actions[0]["uri"].startswith("https://waze.com/ul?ll=46.81,-71.21")


async def test_ahead_excludes_costco(hass: HomeAssistant, notify_calls) -> None:
    _phone(hass)
    await _make_script(hass, has_costco=False)
    await hass.services.async_call("script", "gas", blocking=True)
    assert "Costco" not in notify_calls[0].data["message"]
    assert "Shell (Rouyn-Noranda) dans" in notify_calls[0].data["message"]


async def test_ahead_falls_back_when_stopped(hass: HomeAssistant, notify_calls) -> None:
    _phone(hass, speed=0)
    await _make_script(hass, radius=30)
    await hass.services.async_call("script", "gas", blocking=True)
    data = notify_calls[0].data
    assert "Direction inconnue" in data["title"]
    assert "Costco à" in data["message"]


async def test_nothing_ahead(hass: HomeAssistant, notify_calls) -> None:
    _phone(hass, course=270)
    await _make_script(hass, search_mode="ahead_next")
    await hass.services.async_call("script", "gas", blocking=True)
    assert "Aucune station trouvée dans les 30" in notify_calls[0].data["message"]


async def test_classic_cheapest_still_works(hass: HomeAssistant, notify_calls) -> None:
    _phone(hass)
    await _make_script(hass, search_mode="cheapest", radius=30)
    await hass.services.async_call("script", "gas", blocking=True)
    data = notify_calls[0].data
    assert data["title"].strip() == "Stations les moins chères"
    assert data["message"].strip().startswith("1. Costco à")


async def _until(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.01)


async def test_android_tap_opens_navigation(hass: HomeAssistant, notify_calls) -> None:
    _phone(hass)
    await _make_script(hass, device_os="android", search_mode="ahead_next")
    # The script waits for a tap, so run it in the background.
    task = hass.async_create_background_task(
        hass.services.async_call("script", "gas", blocking=True), "gas script"
    )
    await _until(lambda: len(notify_calls) == 1)

    buttons = notify_calls[0].data["data"]["actions"]
    assert buttons[0]["title"].startswith("📍 #1 Costco (")
    # A tap from an older notification with the old fixed id is ignored.
    hass.bus.async_fire("mobile_app_notification_action", {"action": "NAV_STATION_1"})
    await asyncio.sleep(0.1)
    assert len(notify_calls) == 1

    hass.bus.async_fire("mobile_app_notification_action", {"action": buttons[1]["action"]})
    await _until(lambda: len(notify_calls) == 2)
    await task
    assert notify_calls[1].data["message"] == "command_activity"
    assert notify_calls[1].data["data"]["intent_uri"].startswith("https://waze.com/ul?ll=46.8,-71.2")
