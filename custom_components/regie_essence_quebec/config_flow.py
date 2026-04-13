"""Config flow for Régie Essence Québec."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .const import DOMAIN, CONF_ADDRESS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
from .api_client import RegieEssenceClient

_LOGGER = logging.getLogger(__name__)

class RegieEssenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 5

    def __init__(self) -> None:
        self._stations: list[dict[str, Any]] = []
        self._search_results: list[dict[str, Any]] = []
        
        # Browse state
        self._region: str | None = None
        self._city: str | None = None
        self._brand: str | None = None

    def _get_city(self, address: str) -> str:
        if not address:
            return "Inconnu"
        parts = address.split(",")
        return parts[-1].strip() if len(parts) > 1 else address.strip()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Initial step: Menu to choose Browse or Search."""
        if not self._stations:
            session = async_get_clientsession(self.hass)
            client = RegieEssenceClient(session)
            try:
                self._stations = await client.async_get_all_stations()
            except Exception as err:
                _LOGGER.error("Failed to fetch stations: %s", err)
                return self.async_show_form(step_id="user", errors={"base": "cannot_connect"})

        return self.async_show_menu(
            step_id="user",
            menu_options=["search", "browse"]
        )

    # ==========================================
    # PATH A: ADVANCED MULTI-FIELD SEARCH
    # ==========================================
    async def async_step_search(self, user_input: dict[str, Any] | None = None):
        """Search form with multiple optional fields."""
        errors = {}
        if user_input is not None:
            region_q = user_input.get("search_region", "").lower().strip()
            city_q = user_input.get("search_city", "").lower().strip()
            brand_q = user_input.get("search_brand", "").lower().strip()
            keyword_q = user_input.get("search_keyword", "").lower().strip()

            self._search_results = []
            
            for s in self._stations:
                s_region = s.get("Region", "").lower()
                s_city = self._get_city(s.get("Address", "")).lower()
                s_brand = s.get("brand", "").lower()
                s_addr = s.get("Address", "").lower()
                s_name = s.get("Name", "").lower()

                # Filter logic (skip if it doesn't match the user's input)
                if region_q and region_q not in s_region: continue
                if city_q and city_q not in s_city: continue
                if brand_q and brand_q not in s_brand: continue
                if keyword_q and (keyword_q not in s_addr and keyword_q not in s_name): continue

                self._search_results.append(s)

            if not self._search_results:
                errors["base"] = "no_results_found"
            else:
                return await self.async_step_select_stations()

        # Build the form (all fields optional so the user can enter as little as they want)
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({
                vol.Optional("search_region"): str,
                vol.Optional("search_city"): str,
                vol.Optional("search_brand"): str,
                vol.Optional("search_keyword", description={"suggested_value": "ex: 25 av"}): str,
            }),
            errors=errors
        )

    # ==========================================
    # PATH B: BROWSE BY MENUS
    # ==========================================
    async def async_step_browse(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._region = user_input["flow_region"]
            return await self.async_step_city()

        regions = sorted(list(set(s.get("Region", "Inconnu") for s in self._stations if s.get("Region"))))
        return self.async_show_form(
            step_id="browse",
            data_schema=vol.Schema({vol.Required("flow_region"): vol.In(regions)}),
        )

    async def async_step_city(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._city = user_input["flow_city"]
            return await self.async_step_brand()

        cities = set(self._get_city(s.get("Address")) for s in self._stations if s.get("Region") == self._region)
        return self.async_show_form(
            step_id="city",
            data_schema=vol.Schema({vol.Required("flow_city"): vol.In(sorted(list(cities)))}),
        )

    async def async_step_brand(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._brand = user_input["flow_brand"]
            
            # Pass the filtered results to the common selection step
            self._search_results = [
                s for s in self._stations
                if s.get("Region") == self._region 
                and self._get_city(s.get("Address")) == self._city
                and s.get("brand", "Inconnu") == self._brand
            ]
            return await self.async_step_select_stations()

        brands = set(s.get("brand", "Inconnu") for s in self._stations if s.get("Region") == self._region and self._get_city(s.get("Address")) == self._city)
        return self.async_show_form(
            step_id="brand",
            data_schema=vol.Schema({vol.Required("flow_brand"): vol.In(sorted(list(brands)))}),
        )

    # ==========================================
    # COMMON: MULTI-SELECT RESULTS
    # ==========================================
    async def async_step_select_stations(self, user_input: dict[str, Any] | None = None):
        """Present a multi-select list of whatever stations survived the filters."""
        errors = {}
        if user_input is not None:
            selected_addresses = user_input.get("selected_stations", [])
            if not selected_addresses:
                errors["base"] = "no_selection"
            else:
                return self._create_multiple_entries(selected_addresses)

        # Build options for the dropdown
        options = []
        for s in self._search_results:
            addr = s.get("Address", "")
            brand = s.get("brand", "Inconnu")
            city = self._get_city(addr)
            label = f"{brand} - {city} ({addr})"
            options.append({"value": addr, "label": label})

        return self.async_show_form(
            step_id="select_stations",
            data_schema=vol.Schema({
                vol.Required("selected_stations"): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=True)
                )
            }),
            errors=errors
        )

    # ==========================================
    # THE MAGIC: BULK ADDING
    # ==========================================
    def _create_multiple_entries(self, addresses: list[str]):
        """Creates independent ConfigEntries for every selected station."""
        def get_title(addr: str) -> str:
            for s in self._stations:
                if s.get("Address") == addr:
                    return f"{s.get('brand', 'Inconnu')} - {self._get_city(addr)}"
            return "Station Inconnue"

        # 1. Spawn invisible background imports for every station EXCEPT the first one
        for addr in addresses[1:]:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": config_entries.SOURCE_IMPORT},
                    data={
                        "title": get_title(addr),
                        CONF_ADDRESS: addr,
                    }
                )
            )

        # 2. Return the very first one to naturally conclude the user's UI flow
        first_addr = addresses[0]
        return self.async_create_entry(
            title=get_title(first_addr),
            data={
                CONF_ADDRESS: first_addr,
                "latitude": self.hass.config.latitude,
                "longitude": self.hass.config.longitude,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_MINUTES,
            }
        )

    async def async_step_import(self, user_input: dict[str, Any]):
        """Secret backdoor step used by the background task to bulk-add stations."""
        return self.async_create_entry(
            title=user_input["title"],
            data={
                CONF_ADDRESS: user_input[CONF_ADDRESS],
                "latitude": self.hass.config.latitude,
                "longitude": self.hass.config.longitude,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_MINUTES,
            }
        )

    # ==========================================
    # OPTIONS FLOW (Keep the scan interval settings)
    # ==========================================
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return RegieEssenceOptionsFlow(config_entry)

class RegieEssenceOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, 
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        )
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))
            })
        )
