"""Number platform for Régie Essence Québec."""
from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up the number platform."""
    async_add_entities([RegieEssenceRadiusNumber(entry)])

class RegieEssenceRadiusNumber(RestoreEntity, NumberEntity):
    """Representation of a number entity to hold the search radius."""

    _attr_has_entity_name = True
    _attr_name = "Rayon de recherche"
    _attr_icon = "mdi:map-marker-radius"
    _attr_native_min_value = 1
    _attr_native_max_value = 50
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "km"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        self._attr_unique_id = f"{entry.entry_id}_radius"
        # Attach this entity to your main integration device
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }
        self._attr_native_value = 10.0 # Default starting value

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added and restore its last state."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                self._attr_native_value = float(state.state)
            except ValueError:
                pass

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value when the user moves the slider."""
        self._attr_native_value = value
        self.async_write_ha_state()
