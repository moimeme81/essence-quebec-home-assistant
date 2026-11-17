"""Run the script blueprint inside Home Assistant with a fake phone."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component

from .conftest import ADDR_A
from .test_init import _entry, _setup

BLUEPRINT = Path(__file__).parent.parent / "blueprint" / "script" / "find_gas.yaml"
PHONE = "device_tracker.phone"
# West of stations A and B; driving east (90°) puts both ~15 km ahead.
START = {"latitude": 46.80, "longitude": -71.40}


class FakePhone:
    """Records notifications and answers request_location_update with `next_fix`."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[ServiceCall] = []  # real notifications only
        self.location_requests = 0
        self.next_fix: dict | None = None
        hass.services.async_register("notify", "mobile_app_phone", self._handle)

    async def _handle(self, call: ServiceCall) -> None:
        if call.data.get("message") == "request_location_update":
            self.location_requests += 1
            if self.next_fix is not None:
                self.hass.states.async_set(PHONE, "not_home", self.next_fix, force_update=True)
            return
        self.calls.append(call)

    def set(self, **attrs) -> None:
        self.hass.states.async_set(PHONE, "not_home", attrs)


@pytest.fixture
async def phone(hass: HomeAssistant, feed) -> FakePhone:
    await _setup(hass, _entry(ADDR_A))
    dest = Path(hass.config.path("blueprints/script/regie/find_gas.yaml"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, dest)
    return FakePhone(hass)


async def _make_script(hass: HomeAssistant, **inputs) -> None:
    base = {
        "location_entity": PHONE,
        "notify_phone": PHONE,
        "search_mode": "ahead_best",
        "device_os": "ios",
        "nav_app": "waze",
        # Tests drive the fresh fix explicitly; the default (True) is covered separately.
        "refresh_location": False,
    }
    base.update(inputs)
    assert await async_setup_component(
        hass,
        "script",
        {"script": {"gas": {"use_blueprint": {"path": "regie/find_gas.yaml", "input": base}}}},
    )
    await hass.async_block_till_done()


async def _run(hass: HomeAssistant) -> None:
    await hass.services.async_call("script", "gas", blocking=True)


async def test_ahead_best_with_gps_course(hass: HomeAssistant, phone: FakePhone) -> None:
    phone.set(**START, course=90, speed=25.0)
    await _make_script(hass)
    await _run(hass)

    assert len(phone.calls) == 1
    data = phone.calls[0].data
    assert data["title"].strip() == "Meilleure valeur devant"
    assert "🧭 E (90°) · 90 km/h" in data["message"]
    assert "Costco (Québec) dans" in data["message"]
    assert data["data"]["actions"][0]["uri"].startswith("https://waze.com/ul?ll=46.81,-71.21")


async def test_fresh_fix_is_requested_and_used(hass: HomeAssistant, phone: FakePhone) -> None:
    # Stale fix says stopped; the fresh one (after the request) is moving east.
    phone.set(**START, course=0, speed=0)
    phone.next_fix = {"latitude": 46.80, "longitude": -71.39, "course": 90, "speed": 27}
    await _make_script(hass, refresh_location=True)
    await _run(hass)

    assert phone.location_requests == 1
    assert "🧭 E (90°)" in phone.calls[0].data["message"]
    assert phone.calls[0].data["title"].strip() == "Meilleure valeur devant"


async def test_direction_from_movement_when_no_course(hass: HomeAssistant, phone: FakePhone) -> None:
    # Phone never reports course/speed, but it moved ~1.5 km east between the two fixes.
    phone.set(**START)
    phone.next_fix = {"latitude": 46.80, "longitude": -71.38}
    await _make_script(hass, refresh_location=True)
    await _run(hass)

    msg = phone.calls[0].data["message"]
    assert "selon votre déplacement" in msg
    assert "🧭 E (" in msg
    assert "Costco (Québec) dans" in msg


async def test_ahead_excludes_costco(hass: HomeAssistant, phone: FakePhone) -> None:
    phone.set(**START, course=90, speed=25.0)
    await _make_script(hass, has_costco=False)
    await _run(hass)
    msg = phone.calls[0].data["message"]
    assert "Costco" not in msg
    assert "Shell (Rouyn-Noranda) dans" in msg


async def test_ahead_falls_back_when_stopped(hass: HomeAssistant, phone: FakePhone) -> None:
    phone.set(**START, course=0, speed=0)
    await _make_script(hass, radius=30)
    await _run(hass)
    data = phone.calls[0].data
    assert "Direction inconnue" in data["title"]
    assert "à l’arrêt" in data["message"]
    assert "Costco à" in data["message"]


async def test_no_refresh_wait_when_phone_does_not_answer(hass: HomeAssistant, phone: FakePhone) -> None:
    """If the phone never sends a new fix, the script still answers (after the timeout)."""
    phone.set(**START, course=90, speed=25.0)
    await _make_script(hass, refresh_location=True)
    # Shorten the 15 s wait: run with a patched timeout by firing time forward.
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    task = hass.async_create_background_task(_run(hass), "gas")
    await asyncio.sleep(0.05)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=16))
    await asyncio.wait_for(task, 5)
    assert phone.location_requests == 1
    assert "🧭 E (90°)" in phone.calls[0].data["message"]


async def test_nothing_ahead(hass: HomeAssistant, phone: FakePhone) -> None:
    phone.set(**START, course=270, speed=25.0)
    await _make_script(hass, search_mode="ahead_next")
    await _run(hass)
    assert "Aucune station trouvée dans les 30" in phone.calls[0].data["message"]


async def test_classic_cheapest_still_works(hass: HomeAssistant, phone: FakePhone) -> None:
    phone.set(**START, course=90, speed=25.0)
    await _make_script(hass, search_mode="cheapest", radius=30)
    await _run(hass)
    data = phone.calls[0].data
    assert data["title"].strip() == "Stations les moins chères"
    assert data["message"].strip().startswith("1. Costco à")
    assert "🧭" not in data["message"]


async def _until(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.01)


async def test_android_tap_opens_navigation(hass: HomeAssistant, phone: FakePhone) -> None:
    phone.set(**START, course=90, speed=25.0)
    await _make_script(hass, device_os="android", search_mode="ahead_next")
    # The script waits for a tap, so run it in the background.
    task = hass.async_create_background_task(_run(hass), "gas script")
    await _until(lambda: len(phone.calls) == 1)

    buttons = phone.calls[0].data["data"]["actions"]
    assert buttons[0]["title"].startswith("📍 #1 Costco (")
    # A tap from an older notification with the old fixed id is ignored.
    hass.bus.async_fire("mobile_app_notification_action", {"action": "NAV_STATION_1"})
    await asyncio.sleep(0.1)
    assert len(phone.calls) == 1

    hass.bus.async_fire("mobile_app_notification_action", {"action": buttons[1]["action"]})
    await _until(lambda: len(phone.calls) == 2)
    await task
    assert phone.calls[1].data["message"] == "command_activity"
    assert phone.calls[1].data["data"]["intent_uri"].startswith("https://waze.com/ul?ll=46.8,-71.2")
