"""Config flow for Régie Essence Québec."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_ADDRESS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
from .api_client import RegieEssenceClient

_LOGGER = logging.getLogger(__name__)

class RegieEssenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._stations: list[dict[str, Any]] = []
        self._region: str | None = None
        self._city: str | None = None
        self._brand: str | None = None

    def _get_city(self, address: str) -> str:
        if not address:
            return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors = {}

        if not self._stations:
            session = async_get_clientsession(self.hass)
            client = RegieEssenceClient(session)
            try:
                self._stations = await client.async_get_all_stations()
            except Exception as err:
                _LOGGER.error("Failed to fetch stations: %s", err)
                return self.async_show_form(step_id="user", errors={"base": "cannot_connect"})

        if user_input is not None:
            self._region = user_input["flow_region"]
            return await self.async_step_city()

        regions = sorted(list(set(s.get("Region", "Inconnu") for s in self._stations if s.get("Region"))))
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("flow_region"): vol.In(regions)}),
            errors=errors,
        )

    async def async_step_city(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._city = user_input["flow_city"]
            return await self.async_step_brand()

        cities = set()
        for s in self._stations:
            if s.get("Region") == self._region:
                cities.add(self._get_city(s.get("Address")))

        return self.async_show_form(
            step_id="city",
            data_schema=vol.Schema({vol.Required("flow_city"): vol.In(sorted(list(cities)))}),
        )

    async def async_step_brand(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._brand = user_input["flow_brand"]
            return await self.async_step_station()

        brands = set()
        for s in self._stations:
            if s.get("Region") == self._region and self._get_city(s.get("Address")) == self._city:
                brands.add(s.get("brand", "Inconnu"))

        return self.async_show_form(
            step_id="brand",
            data_schema=vol.Schema({vol.Required("flow_brand"): vol.In(sorted(list(brands)))}),
        )

    async def async_step_station(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            address = user_input["flow_station"]
            title = f"{self._brand} - {self._get_city(address)}"
            
            return self.async_create_entry(
                title=title,
                data={
                    CONF_ADDRESS: address,
                    "latitude": self.hass.config.latitude,
                    "longitude": self.hass.config.longitude,
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_MINUTES,
                },
            )

        stations_map = {}
        for s in self._stations:
            if (s.get("Region") == self._region and 
                self._get_city(s.get("Address")) == self._city and 
                s.get("brand", "Inconnu") == self._brand):
                
                addr = s.get("Address")
                name = s.get("Name", "Station")
                stations_map[addr] = f"{name} ({addr})"

        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema({vol.Required("flow_station"): vol.In(stations_map)}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return RegieEssenceOptionsFlow(config_entry)

class RegieEssenceOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data.update(user_input)
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current_interval = self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440))
            })
        )
