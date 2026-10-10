"""Subscription-driven poller for the Wiener Linien realtime API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import logging
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .api import MonitorSpec, WienerLinienError, fetch_monitor, parse_monitor
from .const import (
    CONF_LINE_ID,
    CONF_STOP_ID,
    CONF_TOWARDS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    IDLE_GRACE,
    MIN_FETCH_SPACING,
    MIN_UPDATE_INTERVAL,
    SUBENTRY_TYPE_MONITOR,
)

_LOGGER = logging.getLogger(__name__)


def signal_update(entry_id: str) -> str:
    """Dispatcher signal name for data updates."""
    return f"wiener_linien_update_{entry_id}"


class SubscriptionHub:
    """Open card subscriptions. Lives in hass.data and survives entry reloads."""

    def __init__(self) -> None:
        self._subs: dict[object, tuple[set[str], Callable[[dict], None]]] = {}
        self.manager: WienerLinienManager | None = None

    @callback
    def async_subscribe(
        self, entity_ids: set[str], send: Callable[[dict], None]
    ) -> CALLBACK_TYPE:
        """Register a viewer for the given sensor entity ids."""
        token = object()
        self._subs[token] = (entity_ids, send)
        self._poke()

        @callback
        def _unsubscribe() -> None:
            if self._subs.pop(token, None) is not None:
                self._poke()

        return _unsubscribe

    @property
    def count(self) -> int:
        """Number of watching cards."""
        return len(self._subs)

    def entity_ids(self) -> set[str]:
        """All watched sensor entity ids."""
        wanted: set[str] = set()
        for ids, _send in self._subs.values():
            wanted |= ids
        return wanted

    def broadcast(self, status: dict) -> None:
        """Send a status event to every viewer."""
        for _ids, send in list(self._subs.values()):
            send(status)

    @callback
    def _poke(self) -> None:
        if self.manager is not None:
            self.manager.async_poke()


class WienerLinienManager:
    """Fetches departures, but only while somebody (a card) is watching."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, hub: SubscriptionHub
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.hub = hub
        self.data: dict[str, dict[str, Any]] = {}
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._last_fetch = 0.0
        self._fetched: set[str] = set()
        self._idle_since: float | None = None

    @property
    def interval(self) -> int:
        """Seconds between two fetches while somebody is watching."""
        value = self.entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        return max(MIN_UPDATE_INTERVAL, int(value))

    # --- lifecycle ---------------------------------------------------------------

    def monitor_ids(self) -> set[str]:
        """All configured monitor (subentry) ids."""
        return {
            s.subentry_id
            for s in self.entry.get_subentries_of_type(SUBENTRY_TYPE_MONITOR)
        }

    @callback
    def async_start(self) -> None:
        """Attach to the hub; resume polling if cards are already watching."""
        self.hub.manager = self
        if self.hub.count:
            self.async_poke()

    @callback
    def async_poke(self) -> None:
        """Subscriptions changed: make sure the loop runs and re-evaluates."""
        self._ensure_running()
        self._wake.set()

    @callback
    def async_stop(self) -> None:
        """Stop polling (config entry unload). Subscriptions stay in the hub."""
        if self.hub.manager is self:
            self.hub.manager = None
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def _wanted(self) -> set[str]:
        """Monitor (subentry) ids that currently have a viewer."""
        registry = er.async_get(self.hass)
        wanted: set[str] = set()
        for entity_id in self.hub.entity_ids():
            entity = registry.async_get(entity_id)
            if (
                entity
                and entity.platform == DOMAIN
                and entity.config_entry_id == self.entry.entry_id
                and entity.unique_id
            ):
                wanted.add(entity.unique_id)
        return wanted & self.monitor_ids()

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._idle_since = None
            self._task = self.entry.async_create_background_task(
                self.hass, self._run(), f"{self.entry.title} poller"
            )

    # --- polling loop ------------------------------------------------------------

    async def _run(self) -> None:
        try:
            while True:
                wanted = self._wanted()
                now = monotonic()
                if wanted:
                    self._idle_since = None
                    due = self._last_fetch + self.interval
                    if wanted - self._fetched or now >= due:
                        pause = self._last_fetch + MIN_FETCH_SPACING - now
                        if pause > 0:
                            await asyncio.sleep(pause)
                        await self._fetch(self._wanted())
                        continue
                    timeout = due - now
                else:
                    if self._idle_since is None:
                        self._idle_since = now
                    timeout = self._idle_since + IDLE_GRACE - now
                    if timeout <= 0:
                        _LOGGER.debug("No viewers left, polling stopped")
                        self._clear()
                        return
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout)
        finally:
            self._task = None

    def _specs(self, ids: set[str]) -> list[MonitorSpec]:
        specs = []
        for sub in self.entry.get_subentries_of_type(SUBENTRY_TYPE_MONITOR):
            if sub.subentry_id in ids:
                specs.append(
                    MonitorSpec(
                        key=sub.subentry_id,
                        stop_id=int(sub.data[CONF_STOP_ID]),
                        line_id=int(sub.data[CONF_LINE_ID]),
                        towards=sub.data.get(CONF_TOWARDS, ""),
                    )
                )
        return specs

    async def _fetch(self, ids: set[str]) -> None:
        specs = self._specs(ids)
        self._last_fetch = monotonic()
        self._fetched = set(ids)
        if not specs:
            return
        session = async_get_clientsession(self.hass)
        try:
            raw = await fetch_monitor(session, [s.stop_id for s in specs])
            parsed = parse_monitor(raw, specs)
        except WienerLinienError as err:
            if self.last_error != str(err):
                _LOGGER.warning("Fetching departures failed: %s", err)
            self.last_error = str(err)
            self._notify(ok=False)
            return
        except Exception:  # noqa: BLE001 - never let the poller die
            _LOGGER.exception("Unexpected error while fetching departures")
            self.last_error = "unexpected error"
            self._notify(ok=False)
            return
        self.last_error = None
        updated = dt_util.utcnow().isoformat().replace("+00:00", "Z")
        for item in parsed.values():
            item["updated"] = updated
        self.data = parsed
        self._notify(ok=True)

    def _clear(self) -> None:
        self.data = {}
        self._fetched = set()
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    def _notify(self, *, ok: bool) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
        self.hub.broadcast(
            {
                "ok": ok,
                "error": self.last_error,
                "updated": dt_util.utcnow().isoformat(),
            }
        )
