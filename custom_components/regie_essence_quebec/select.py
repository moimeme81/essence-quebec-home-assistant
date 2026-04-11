"""Select platform for Régie Essence Québec."""
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    async_add_entities([RegieEssenceGasTypeSelect(entry)])

class RegieEssenceGasTypeSelect(RestoreEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Type d'essence"
    _attr_icon = "mdi:gas-station"
    _attr_options = ["Régulier", "Super", "Diesel"]

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_gas_type"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Régie Essence Québec",
            "manufacturer": "Service Hub",
        }
        self._attr_current_option = "Régulier"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.state in self._attr_options:
            self._attr_current_option = state.state

    async def async_select_option(self, option: str) -> None:
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()
