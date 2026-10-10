"""Config flow: one entry, departure monitors as subentries."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.storage import Store

from .api import (
    WienerLinienApiError,
    WienerLinienError,
    fetch_monitor,
    normalize,
)
from .catalog import (
    CATALOG_VERSION,
    CatalogError,
    direction_options,
    download_catalog,
    is_fresh,
    line_options,
    stop_name_options,
)
from .const import (
    CONF_LINE,
    CONF_LINE_ID,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_TOWARDS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    SUBENTRY_TYPE_MONITOR,
)

_LOGGER = logging.getLogger(__name__)
_CATALOG_KEY = f"{DOMAIN}_catalog"


async def async_get_catalog(hass: HomeAssistant) -> dict[str, Any]:
    """Return the open-data catalog (memory -> storage -> download)."""
    cached = hass.data.get(_CATALOG_KEY)
    if is_fresh(cached):
        return cached
    store: Store[dict[str, Any]] = Store(hass, 1, "wiener_linien_catalog")
    saved = await store.async_load()
    if is_fresh(saved):
        hass.data[_CATALOG_KEY] = saved
        return saved
    try:
        catalog = await download_catalog(async_get_clientsession(hass))
    except CatalogError:
        if saved and saved.get("version") == CATALOG_VERSION:
            hass.data[_CATALOG_KEY] = saved
            return saved
        raise
    await store.async_save(catalog)
    hass.data[_CATALOG_KEY] = catalog
    return catalog


def monitor_title(line: str, stop_name: str, towards: str) -> str:
    """Display name of a monitor."""
    return f"{line} {stop_name}" + (f" → {towards}" if towards else "")


def monitor_unique_id(stop_id: int, line_id: int, towards: str) -> str:
    """Unique id of a monitor subentry."""
    return f"{stop_id}_{line_id}_{normalize(towards)}"


class WienerLinienConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Wiener Linien."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow (update interval)."""
        return WienerLinienOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the supported subentry types."""
        return {SUBENTRY_TYPE_MONITOR: MonitorSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the (single) entry; monitors are added as subentries."""
        if user_input is not None:
            return self.async_create_entry(title="Wiener Linien", data={})
        return self.async_show_form(step_id="user")


class WienerLinienOptionsFlow(OptionsFlow):
    """Options: how often the API is queried while a card is visible."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the update interval."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL])}
            )
        current = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_UPDATE_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )


class MonitorSubentryFlow(ConfigSubentryFlow):
    """Add or change a departure monitor."""

    def __init__(self) -> None:
        self._catalog: dict[str, Any] = {}
        self._line_id = ""
        self._stop_name = ""
        self._directions: list[dict[str, Any]] = []

    # --- entry point --------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose between guided search and manual ids."""
        return self.async_show_menu(step_id="user", menu_options=["search", "manual"])

    # --- guided search: line -> stop -> destination ---------------------------------

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the line."""
        if not self._catalog:
            try:
                self._catalog = await async_get_catalog(self.hass)
            except CatalogError as err:
                _LOGGER.warning("Could not load Wiener Linien open data: %s", err)
                return await self.async_step_manual(catalog_failed=True)
        if user_input is not None:
            self._line_id = user_input[CONF_LINE]
            return await self.async_step_stop()
        options = [
            SelectOptionDict(value=line_id, label=label)
            for line_id, label in line_options(
                self._catalog, self.hass.config.language[:2]
            )
        ]
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LINE): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the stop."""
        if user_input is not None:
            self._stop_name = user_input["stop"]
            return await self.async_step_direction()
        options = [
            SelectOptionDict(value=name, label=name)
            for name in stop_name_options(self._catalog, self._line_id)
        ]
        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema(
                {
                    vol.Required("stop"): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
            description_placeholders={
                "line": self._catalog["lines"][self._line_id][0]
            },
        )

    async def async_step_direction(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the destination (this also decides the platform/RBL)."""
        if not self._directions:
            self._directions = direction_options(
                self._catalog, self._line_id, self._stop_name
            )
        if user_input is not None:
            choice = self._directions[int(user_input["direction"])]
            return self._create(
                stop_id=choice["stop_id"],
                line_id=int(self._line_id),
                line=self._catalog["lines"][self._line_id][0],
                stop_name=self._stop_name,
                towards=choice["towards"],
            )
        options = [
            SelectOptionDict(
                value=str(i), label=f"→ {d['towards']}  (RBL {d['stop_id']})"
            )
            for i, d in enumerate(self._directions)
        ]
        return self.async_show_form(
            step_id="direction",
            data_schema=vol.Schema(
                {
                    vol.Required("direction"): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
            description_placeholders={
                "line": self._catalog["lines"][self._line_id][0],
                "stop": self._stop_name,
            },
        )

    # --- manual ids -------------------------------------------------------------------

    async def async_step_manual(
        self,
        user_input: dict[str, Any] | None = None,
        catalog_failed: bool = False,
    ) -> SubentryFlowResult:
        """Enter the stop id (RBL) and optionally line id and destination."""
        errors: dict[str, str] = {}
        placeholders = {"lines": ""}
        if catalog_failed:
            errors["base"] = "catalog_unavailable"
        if user_input is not None:
            stop_id = int(user_input[CONF_STOP_ID])
            wanted_line = user_input.get(CONF_LINE_ID)
            towards = (user_input.get(CONF_TOWARDS) or "").strip()
            try:
                raw = await fetch_monitor(
                    async_get_clientsession(self.hass), [stop_id]
                )
            except WienerLinienApiError as err:
                errors["base"] = "stop_not_found" if err.code == 312 else "api_error"
            except WienerLinienError:
                errors["base"] = "cannot_connect"
            else:
                found = {}
                stop_title = ""
                for monitor in (raw.get("data") or {}).get("monitors") or []:
                    props = (monitor.get("locationStop") or {}).get("properties", {})
                    if (props.get("attributes") or {}).get("rbl") != stop_id:
                        continue
                    stop_title = props.get("title", "")
                    for line in monitor.get("lines") or []:
                        found[int(line["lineId"])] = line
                if not found:
                    errors[CONF_STOP_ID] = "stop_not_found"
                elif wanted_line:
                    wanted_line = int(wanted_line)
                    if wanted_line not in found:
                        errors[CONF_LINE_ID] = "line_not_found"
                        placeholders["lines"] = _describe(found)
                elif len(found) > 1:
                    errors[CONF_LINE_ID] = "line_required"
                    placeholders["lines"] = _describe(found)
                else:
                    wanted_line = next(iter(found))
                if not errors:
                    line = found[wanted_line]
                    return self._create(
                        stop_id=stop_id,
                        line_id=wanted_line,
                        line=line.get("name", ""),
                        stop_name=stop_title,
                        towards=towards or line.get("towards", ""),
                    )
        schema = vol.Schema(
            {
                vol.Required(CONF_STOP_ID): vol.Coerce(int),
                vol.Optional(CONF_LINE_ID): vol.Coerce(int),
                vol.Optional(CONF_TOWARDS): str,
            }
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    # --- reconfigure: change the destination filter ---------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the destination used to highlight deviating vehicles."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            towards = (user_input.get(CONF_TOWARDS) or "").strip()
            return self.async_update_and_abort(
                entry,
                subentry,
                data_updates={CONF_TOWARDS: towards},
                title=monitor_title(
                    subentry.data[CONF_LINE], subentry.data[CONF_STOP_NAME], towards
                ),
                unique_id=monitor_unique_id(
                    subentry.data[CONF_STOP_ID], subentry.data[CONF_LINE_ID], towards
                ),
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Optional(CONF_TOWARDS): str}),
                {CONF_TOWARDS: subentry.data.get(CONF_TOWARDS, "")},
            ),
        )

    # --- helpers ------------------------------------------------------------------------

    def _create(
        self,
        *,
        stop_id: int,
        line_id: int,
        line: str,
        stop_name: str,
        towards: str,
    ) -> SubentryFlowResult:
        unique_id = monitor_unique_id(stop_id, line_id, towards)
        if any(s.unique_id == unique_id for s in self._get_entry().subentries.values()):
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=monitor_title(line, stop_name, towards),
            data={
                CONF_STOP_ID: stop_id,
                CONF_LINE_ID: line_id,
                CONF_LINE: line,
                CONF_STOP_NAME: stop_name,
                CONF_TOWARDS: towards,
            },
            unique_id=unique_id,
        )


def _describe(found: dict[int, dict]) -> str:
    return ", ".join(f"{line.get('name')} ({line_id})" for line_id, line in found.items())
