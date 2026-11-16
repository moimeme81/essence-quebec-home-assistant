"""Constants for the Régie Essence Québec integration."""

DOMAIN = "regie_essence_quebec"

# The Régie publishes new prices a few times a day; polling more often only
# re-downloads the same province-wide file.
DEFAULT_SCAN_INTERVAL_MINUTES = 60
MIN_SCAN_INTERVAL_MINUTES = 15
MAX_SCAN_INTERVAL_MINUTES = 1440

CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_ADDRESS = "address"
CONF_SCAN_INTERVAL = "scan_interval"

# Key under hass.data[DOMAIN] holding the single shared coordinator.
DATA_COORDINATOR = "coordinator"

MAX_SEARCH_RADIUS_KM = 100

# Canonical fuel ids -> every spelling seen (or plausibly seen) in the feed.
FUEL_ALIASES: dict[str, tuple[str, ...]] = {
    "regular": ("régulier", "regulier", "ordinaire", "regular"),
    "super": ("super", "premium", "suprême", "supreme"),
    "diesel": ("diesel", "diésel"),
}

TREND_UP = "up"
TREND_DOWN = "down"
TREND_STABLE = "stable"
TRENDS = [TREND_UP, TREND_DOWN, TREND_STABLE]
