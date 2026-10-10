"""Websocket API: cards subscribe here so the integration knows it is watched."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_subscribe)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wiener_linien/subscribe",
        vol.Required("entity_ids"): [str],
    }
)
@callback
def ws_subscribe(hass: HomeAssistant, connection, msg: dict) -> None:
    """Subscribe to departure updates for the given sensors.

    Data is polled from the API as long as at least one subscription is open.
    The subscription is dropped automatically when the websocket closes.
    """
    registry = er.async_get(hass)
    entity_ids = {
        entity_id
        for entity_id in msg["entity_ids"]
        if (entity := registry.async_get(entity_id)) and entity.platform == DOMAIN
    }
    msg_id = msg["id"]

    @callback
    def send(status: dict) -> None:
        connection.send_message(websocket_api.event_message(msg_id, status))

    hub = hass.data[DOMAIN]
    connection.subscriptions[msg_id] = hub.async_subscribe(entity_ids, send)
    connection.send_result(msg_id, {"interval": hub.manager.interval if hub.manager else DEFAULT_UPDATE_INTERVAL})
