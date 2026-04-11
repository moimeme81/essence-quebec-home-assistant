"""Config flow for Régie Essence Québec."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
from .api_client import RegieEssenceClient

_LOGGER = logging.getLogger(__name__)

class RegieEssenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Initial setup: Create the Master Hub (Only allow one instance)."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Régie Essence Québec", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return RegieEssenceOptionsFlow(config_entry)


class RegieEssenceOptionsFlow(config_entries.OptionsFlow):
    """Handle options to add/remove stations."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._stations_api_data: list[dict[str, Any]] = []
        self._region: str | None = None
        self._city: str | None = None
        self._brand: str | None = None

    def _get_city(self, address: str) -> str:
        if not address: return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Main menu for the Hub."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_station", "remove_station"]
        )

    async def async_step_add_station(self, user_input: dict[str, Any] | None = None):
        """Start the process to add a new station."""
        if not self._stations_api_data:
            session = async_get_clientsession(self.hass)
            client = RegieEssenceClient(session)
            self._stations_api_data = await client.async_get_all_stations()

        if user_input is not None:
            self._region = user_input["flow_region"]
            return await self.async_step_city()

        regions = sorted(list(set(s.get("Region", "Inconnu") for s in self._stations_api_data if s.get("Region"))))
        return self.async_show_form(
            step_id="add_station",
            data_schema=vol.Schema({vol.Required("flow_region"): vol.In(regions)}),
        )

    async def async_step_city(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._city = user_input["flow_city"]
            return await self.async_step_brand()

        cities = set(self._get_city(s.get("Address")) for s in self._stations_api_data if s.get("Region") == self._region)
        return self.async_show_form(
            step_id="city",
            data_schema=vol.Schema({vol.Required("flow_city"): vol.In(sorted(list(cities)))}),
        )

    async def async_step_brand(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._brand = user_input["flow_brand"]
            return await self.async_step_select_station()

        brands = set(s.get("brand", "Inconnu") for s in self._stations_api_data if s.get("Region") == self._region and self._get_city(s.get("Address")) == self._city)
        return self.async_show_form(
            step_id="brand",
            data_schema=vol.Schema({vol.Required("flow_brand"): vol.In(sorted(list(brands)))}),
        )

    async def async_step_select_station(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            address = user_input["flow_station"]
            
            # Save the station to the Hub's options
            new_options = dict(self.config_entry.options)
            stations_list = new_options.setdefault("stations", [])
            if address not in stations_list:
                stations_list.append(address)
            
            self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)
            return self.async_create_entry(title="", data={})

        stations_map = {
            s.get("Address"): f"{s.get('Name', 'Station')} ({s.get('Address')})"
            for s in self._stations_api_data
            if s.get("Region") == self._region and self._get_city(s.get("Address")) == self._city and s.get("brand", "Inconnu") == self._brand
        }
        return self.async_show_form(
            step_id="select_station",
            data_schema=vol.Schema({vol.Required("flow_station"): vol.In(stations_map)}),
        )

    async def async_step_remove_station(self, user_input: dict[str, Any] | None = None):
        """Remove a station from the Hub."""
        current_stations = self.config_entry.options.get("stations", [])
        
        if user_input is not None:
            address_to_remove = user_input["remove_target"]
            new_options = dict(self.config_entry.options)
            if address_to_remove in new_options.get("stations", []):
                new_options["stations"].remove(address_to_remove)
            
            self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)
            return self.async_create_entry(title="", data={})

        if not current_stations:
            return self.async_abort(reason="no_stations_configured")

        return self.async_show_form(
            step_id="remove_station",
            data_schema=vol.Schema({vol.Required("remove_target"): vol.In(current_stations)}),
        )
