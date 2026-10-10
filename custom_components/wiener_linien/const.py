"""Constants for the Wiener Linien integration."""

from __future__ import annotations

DOMAIN = "wiener_linien"

SUBENTRY_TYPE_MONITOR = "monitor"

CONF_STOP_ID = "stop_id"
CONF_LINE_ID = "line_id"
CONF_LINE = "line"
CONF_STOP_NAME = "stop_name"
CONF_TOWARDS = "towards"

API_URL = "https://www.wienerlinien.at/ogd_realtime/monitor"
OGD_BASE_URL = "https://www.wienerlinien.at/ogd_realtime/doku/ogd/"

# Poll only while at least one card is subscribed. The API allows roughly
# 10 requests per 30 s; all stops are fetched in a single request.
CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 30  # seconds between fetches while subscribed
MIN_UPDATE_INTERVAL = 15
MAX_UPDATE_INTERVAL = 300
MIN_FETCH_SPACING = 5  # seconds, lower bound between two fetches
IDLE_GRACE = 60  # seconds to keep polling after the last card unsubscribed
MAX_DEPARTURES = 10

CARD_URL = "/wiener_linien/wiener-linien-card.js"
