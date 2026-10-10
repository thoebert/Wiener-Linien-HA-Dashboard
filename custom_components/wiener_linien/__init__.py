"""Wiener Linien departures for Home Assistant."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CARD_URL, DOMAIN
from .manager import SubscriptionHub, WienerLinienManager
from .websocket import async_register_websocket

PLATFORMS = ["sensor"]

type WienerLinienConfigEntry = ConfigEntry[WienerLinienManager]


class CardView(HomeAssistantView):
    """Serve the card; `no-cache` makes browsers revalidate after every update."""

    url = CARD_URL
    name = "api:wiener_linien:card"
    requires_auth = False

    def __init__(self, path: Path) -> None:
        self._path = path

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Return the card module."""
        return web.FileResponse(self._path, headers={"Cache-Control": "no-cache"})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the card and the websocket command."""
    card = Path(__file__).parent / "www" / "wiener-linien-card.js"
    hass.http.register_view(CardView(card))
    frontend.add_extra_js_url(hass, CARD_URL)
    hass.data[DOMAIN] = SubscriptionHub()
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WienerLinienConfigEntry) -> bool:
    """Set up Wiener Linien from a config entry."""
    manager = WienerLinienManager(hass, entry, hass.data[DOMAIN])
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WienerLinienConfigEntry) -> bool:
    """Unload a config entry."""
    entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: WienerLinienConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
