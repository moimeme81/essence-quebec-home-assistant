"""Shared DataUpdateCoordinator for Régie Essence Québec.

The Régie publishes a single province-wide file, so one coordinator downloads it
for every configured station instead of one download per config entry.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import RegieEssenceClient
from .const import (
    CONF_ADDRESS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    TREND_STABLE,
)
from .helpers import compute_trend, parse_price

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_prices_memory"
STORAGE_VERSION = 1


def entry_scan_interval(entry: ConfigEntry) -> int:
    """Scan interval (minutes) requested by an entry, clamped to the allowed range."""
    value = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
    )
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_SCAN_INTERVAL_MINUTES
    return max(MIN_SCAN_INTERVAL_MINUTES, min(MAX_SCAN_INTERVAL_MINUTES, value))


class RegieEssenceCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Downloads all stations once and tracks price trends for monitored ones.

    Data is a dict keyed by station address.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            # Shared by every entry of the integration, so not bound to one of them.
            config_entry=None,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES),
        )
        self.client = RegieEssenceClient(async_get_clientsession(hass))
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._memory: dict[str, dict[str, dict[str, Any]]] | None = None
        # entry_id -> (monitored address, requested interval in minutes)
        self._entries: dict[str, tuple[str, int]] = {}

    # ------------------------------------------------------------------
    # Entry bookkeeping
    # ------------------------------------------------------------------
    @property
    def has_entries(self) -> bool:
        return bool(self._entries)

    @property
    def monitored_addresses(self) -> set[str]:
        return {address for address, _ in self._entries.values()}

    def register_entry(self, entry: ConfigEntry) -> None:
        self._entries[entry.entry_id] = (entry.data.get(CONF_ADDRESS, ""), entry_scan_interval(entry))
        self._recompute_interval()

    def unregister_entry(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)
        self._recompute_interval()

    def _recompute_interval(self) -> None:
        """Poll as often as the most demanding entry asked for."""
        minutes = min(
            (interval for _, interval in self._entries.values()),
            default=DEFAULT_SCAN_INTERVAL_MINUTES,
        )
        self.update_interval = timedelta(minutes=minutes)

    async def async_apply_trends_for(self, address: str) -> None:
        """Fill in trends for a station that was added after the last refresh."""
        if not self.data or address not in self.data:
            return
        await self._async_load_memory()
        if self._process_station(self.data[address]):
            await self._store.async_save(self._memory)
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # Trend memory
    # ------------------------------------------------------------------
    async def _async_load_memory(self) -> None:
        if self._memory is None:
            self._memory = await self._store.async_load() or {}

    def _process_station(self, station: dict[str, Any]) -> bool:
        """Inject 'Tendency' into each price of a monitored station. Returns True if memory changed."""
        assert self._memory is not None
        address = station["Address"]
        station_memory = self._memory.setdefault(address, {})
        changed = False

        for gas in station.get("Prices", []):
            gas_type = gas.get("GasType")
            if not gas_type:
                continue

            old = station_memory.get(gas_type) or {}
            old_price = old.get("price")
            # Old versions stored 0.0 for missing prices; treat that as unknown.
            if not old_price:
                old_price = None

            price = parse_price(gas.get("Price"))
            if price is None:
                # Price temporarily missing (N/D): keep the last known trend, don't record anything.
                gas["Tendency"] = old.get("tendency", TREND_STABLE)
                continue

            trend = compute_trend(old_price, old.get("tendency"), price)
            gas["Tendency"] = trend
            if old_price != price or old.get("tendency") != trend:
                station_memory[gas_type] = {"price": price, "tendency": trend}
                changed = True

        return changed

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            all_stations = await self.client.async_get_all_stations()
        except Exception as err:  # noqa: BLE001 - surface any fetch/parse failure as UpdateFailed
            raise UpdateFailed(f"Error fetching Régie data: {err}") from err

        await self._async_load_memory()
        monitored = self.monitored_addresses
        memory_changed = False
        processed: dict[str, dict[str, Any]] = {}

        for station in all_stations:
            address = station.get("Address")
            if not address:
                continue
            if address in monitored:
                memory_changed |= self._process_station(station)
            else:
                for gas in station.get("Prices", []):
                    gas["Tendency"] = TREND_STABLE
            processed[address] = station

        if memory_changed:
            await self._store.async_save(self._memory)

        return processed
