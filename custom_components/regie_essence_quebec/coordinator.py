"""DataUpdateCoordinator for Régie Essence Québec."""
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .const import DOMAIN, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
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
        """Nettoie la chaîne '186.9¢' en un nombre flottant 186.9 pour la comparaison."""
        if not price_str:
            return 0.0
        try:
            # On retire le symbole '¢' et les espaces, puis on convertit
            return float(price_str.replace("¢", "").replace("C", "").strip())
        except ValueError:
            return 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            # 1. Récupération des données fraîches de l'API
            all_stations = await self._client.async_get_all_stations()
        except Exception as err:
            raise UpdateFailed(f"Network error fetching API data: {err}") from err

        # 2. Chargement de la mémoire depuis le disque (seulement au premier passage)
        if self._memory is None:
            self._memory = await self.store.async_load() or {}

        memory_changed = False
        processed_stations = {}

        # 3. Traitement, Comparaison et Injection
        for station in all_stations:
            address = station.get("Address")
            if not address:
                continue

            # Création du profil de la station dans la mémoire si elle n'existe pas
            if address not in self._memory:
                self._memory[address] = {}

            # Analyse de chaque type d'essence (Régulier, Super, Diesel)
            for gas in station.get("Prices", []):
                gas_type = gas.get("GasType")
                price_str = gas.get("Price")
                
                if not gas_type or not price_str:
                    continue

                current_price = self._parse_price(price_str)
                
                # Récupération de l'historique pour CE type d'essence précis
                history = self._memory[address].get(gas_type, {"price": current_price, "tendency": "stable"})
                old_price = history["price"]
                tendency = history["tendency"]

                # Évaluation de la tendance uniquement si le prix a changé
                if current_price > old_price:
                    tendency = "up"
                    memory_changed = True
                elif current_price < old_price:
                    tendency = "down"
                    memory_changed = True
                
                # Mise à jour de la mémoire interne
                if current_price != old_price:
                    self._memory[address][gas_type] = {
                        "price": current_price, 
                        "tendency": tendency
                    }

                # MAGIE : On injecte la tendance directement dans le dictionnaire de l'API !
                gas["Tendency"] = tendency

            processed_stations[address] = station

        # 4. Sauvegarde de la mémoire sur le disque UNIQUEMENT s'il y a eu des changements
        if memory_changed:
            await self.store.async_save(self._memory)

        return processed_stations
