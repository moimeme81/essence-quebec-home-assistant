"""DataUpdateCoordinator for Régie Essence Québec."""
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .const import DOMAIN, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES, CONF_ADDRESS
from .api_client import RegieEssenceClient

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_prices_memory"
STORAGE_VERSION = 1

class RegieEssenceCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        session = async_get_clientsession(hass)
        self._client = RegieEssenceClient(session)
        
        # Initialisation de la mémoire persistante de Home Assistant
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._memory = None
        
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, 
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )

    def _parse_price(self, price_str: str) -> float:
        """Nettoie la chaîne '186.9¢' en un nombre flottant 186.9."""
        if not price_str:
            return 0.0
        try:
            return float(price_str.replace("¢", "").replace("C", "").strip())
        except ValueError:
            return 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            # 1. Récupération des données globales
            all_stations = await self._client.async_get_all_stations()
        except Exception as err:
            raise UpdateFailed(f"Network error fetching API data: {err}") from err

        # 2. Chargement de la mémoire persistante au premier démarrage
        if self._memory is None:
            self._memory = await self.store.async_load() or {}

        memory_changed = False
        processed_stations = {}
        
        # On identifie la SEULE station qui nous intéresse pour l'historique
        monitored_address = self.config_entry.data.get(CONF_ADDRESS)

        # 3. Analyse et détection des tendances
        for station in all_stations:
            address = station.get("Address")
            if not address:
                continue

            # Si ce n'est PAS la station surveillée, on passe son tour pour la mémoire
            if address != monitored_address:
                # On injecte juste "stable" par défaut pour que les données restent uniformes
                for gas in station.get("Prices", []):
                    gas["Tendency"] = "stable"
                processed_stations[address] = station
                continue

            # --- À PARTIR D'ICI : On ne traite QUE la station surveillée ---
            if address not in self._memory:
                self._memory[address] = {}

            for gas in station.get("Prices", []):
                gas_type = gas.get("GasType")
                price_str = gas.get("Price")
                
                if not gas_type or not price_str:
                    continue

                current_price = self._parse_price(price_str)
                old_data = self._memory[address].get(gas_type)
                
                if old_data is None:
                    # Première rencontre avec cette station/essence
                    tendency = "stable"
                    memory_changed = True
                else:
                    old_price = old_data["price"]
                    tendency = old_data["tendency"]
                    
                    # Comparaison pour déterminer la tendance
                    if current_price > old_price:
                        tendency = "up"
                        memory_changed = True
                    elif current_price < old_price:
                        tendency = "down"
                        memory_changed = True
                    # Si current_price == old_price, on garde la tendance actuelle (up/down/stable)

                # Mise à jour systématique de la mémoire vive
                self._memory[address][gas_type] = {
                    "price": current_price,
                    "tendency": tendency
                }

                # Injection de la tendance pour les capteurs et services
                gas["Tendency"] = tendency

            processed_stations[address] = station

        # 4. Sauvegarde physique uniquement si une valeur a changé pour la station surveillée
        if memory_changed:
            await self.store.async_save(self._memory)

        return processed_stations
