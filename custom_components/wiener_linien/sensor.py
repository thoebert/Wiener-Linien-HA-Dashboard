"""One sensor per configured line/stop/destination."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import WienerLinienConfigEntry
from .const import (
    CONF_LINE,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_TOWARDS,
    DOMAIN,
    SUBENTRY_TYPE_MONITOR,
)
from .manager import WienerLinienManager, signal_update

_ATTRS = frozenset(
    {
        "available",
        "updated",
        "line",
        "line_id",
        "line_type",
        "line_color",
        "platform",
        "api_towards",
        "departures",
        "disturbances",
        "stop_id",
        "stop_name",
        "towards",
        "update_interval",
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WienerLinienConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a sensor for every monitor subentry."""
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_MONITOR):
        async_add_entities(
            [WienerLinienSensor(entry.runtime_data, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class WienerLinienSensor(SensorEntity):
    """Next departure of one line at one stop (all details as attributes)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:tram"
    # Departure lists are large and only meaningful live: keep them out of the DB.
    _unrecorded_attributes = _ATTRS

    def __init__(self, manager: WienerLinienManager, subentry: ConfigSubentry) -> None:
        self._manager = manager
        self._subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Wiener Linien",
            entry_type=None,
        )

    async def async_added_to_hass(self) -> None:
        """Listen for new data."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self._manager.entry.entry_id), self._refresh
            )
        )

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()

    @property
    def _data(self) -> dict[str, Any]:
        return self._manager.data.get(self._subentry.subentry_id) or {}

    @property
    def native_value(self) -> datetime | None:
        """Time of the next departure."""
        now = dt_util.utcnow()
        for dep in self._data.get("departures", []):
            when = dt_util.parse_datetime(dep["real"] or dep["planned"])
            if when and when >= now:
                return when
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything the card needs."""
        attrs = {
            "stop_id": self._subentry.data[CONF_STOP_ID],
            "stop_name": self._subentry.data.get(CONF_STOP_NAME),
            "towards": self._subentry.data.get(CONF_TOWARDS),
            "line": self._subentry.data.get(CONF_LINE),
            "update_interval": self._manager.interval,
        }
        attrs.update(self._data)
        return attrs
