"""Wiener Linien realtime API client and parser (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

import aiohttp

from .const import API_URL, MAX_DEPARTURES

METRO_COLORS = {
    "U1": "#e3000f",
    "U2": "#a862a4",
    "U3": "#db7607",
    "U4": "#01963e",
    "U5": "#008f95",
    "U6": "#9d6830",
}
TYPE_COLORS = {
    "ptBusCity": "#0b295d",
    "ptBusNight": "#0b295d",
    "ptRufBus": "#0b295d",
    "ptTram": "#c00a09",
    "ptTramWLB": "#c00a09",
    "ptTrainS": "#0089c4",
    "ptTrain": "#e2002a",
    "ptTrainR": "#e2002a",
}
DEFAULT_COLOR = "#e30014"


class WienerLinienError(Exception):
    """Base error."""


class WienerLinienConnectionError(WienerLinienError):
    """Network or HTTP error."""


class WienerLinienApiError(WienerLinienError):
    """The API returned an error message."""

    def __init__(self, code: int | None, text: str) -> None:
        super().__init__(f"API error {code}: {text}")
        self.code = code


@dataclass(frozen=True)
class MonitorSpec:
    """What one sensor wants to see."""

    key: str
    stop_id: int
    line_id: int
    towards: str = ""


def line_color(line_name: str | None, line_type: str | None) -> str:
    """Return the Wiener Linien colour of a line."""
    if line_name and line_name.upper() in METRO_COLORS:
        return METRO_COLORS[line_name.upper()]
    return TYPE_COLORS.get(line_type or "", DEFAULT_COLOR)


def normalize(text: str) -> str:
    """Lower-case and strip everything but letters and digits."""
    return re.sub(r"[^0-9a-zäöüß]", "", (text or "").casefold())


def deviates(expected: str, actual: str) -> bool:
    """True if a vehicle's destination differs from the configured one."""
    exp = normalize(expected)
    if not exp:
        return False
    act = normalize(actual)
    return not (act.startswith(exp) or exp.startswith(act))


def _to_utc_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_title(title: str) -> str:
    """Drop a leading line list such as '5, 6: ' and flatten line breaks."""
    colon = title.find(":")
    if colon != -1:
        prefix = title[:colon]
        if len(prefix) < 3 + 4 * prefix.count(","):
            title = title[colon + 1 :]
    return re.sub(r"\s*\n\s*", ". ", title.strip())


def build_url(stop_ids: list[int]) -> str:
    """Build the monitor URL for the given stops."""
    params = "".join(f"stopId={s}&" for s in sorted(set(stop_ids)))
    return (
        f"{API_URL}?{params}activateTrafficInfo=stoerungkurz"
        "&activateTrafficInfo=stoerunglang"
    )


async def fetch_monitor(
    session: aiohttp.ClientSession, stop_ids: list[int]
) -> dict[str, Any]:
    """Fetch the raw monitor response."""
    try:
        async with session.get(
            build_url(stop_ids), timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status == 429:
                raise WienerLinienApiError(429, "rate limit exceeded")
            resp.raise_for_status()
            raw = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise WienerLinienConnectionError(str(err)) from err
    message = raw.get("message") or {}
    code = message.get("messageCode")
    if code not in (1, None):
        raise WienerLinienApiError(code, str(message.get("value")))
    return raw


def parse_monitor(raw: dict[str, Any], specs: list[MonitorSpec]) -> dict[str, dict]:
    """Turn a raw response into per-spec data (JSON-able dicts)."""
    data = raw.get("data") or {}
    traffic_infos = data.get("trafficInfos") or []
    categories = {c.get("id"): c.get("name") for c in data.get("trafficInfoCategories") or []}
    lines: dict[tuple[int, int], dict] = {}
    for monitor in data.get("monitors") or []:
        attrs = (monitor.get("locationStop") or {}).get("properties", {}).get(
            "attributes", {}
        )
        rbl = attrs.get("rbl")
        for line in monitor.get("lines") or []:
            lines[(int(rbl), int(line.get("lineId")))] = line

    fetched = _to_utc_iso((raw.get("message") or {}).get("serverTime")) or datetime.now(
        timezone.utc
    ).isoformat().replace("+00:00", "Z")

    result: dict[str, dict] = {}
    for spec in specs:
        line = lines.get((spec.stop_id, spec.line_id))
        if line is None:
            result[spec.key] = {
                "available": False,
                "updated": fetched,
                "departures": [],
                "disturbances": [],
            }
            continue
        line_name = line.get("name") or ""
        departures = []
        for dep in ((line.get("departures") or {}).get("departure") or [])[
            :MAX_DEPARTURES
        ]:
            times = dep.get("departureTime") or {}
            vehicle = dep.get("vehicle") or {}
            planned = _to_utc_iso(times.get("timePlanned"))
            real = _to_utc_iso(times.get("timeReal"))
            if not (planned or real):
                continue
            towards = vehicle.get("towards") or line.get("towards") or ""
            departures.append(
                {
                    "planned": planned,
                    "real": real,
                    "realtime": real is not None,
                    "towards": towards,
                    "deviates": deviates(spec.towards, towards),
                    "traffic_jam": bool(vehicle.get("trafficjam")),
                    "barrier_free": bool(vehicle.get("barrierFree", True)),
                }
            )
        disturbances = []
        seen: set[str] = set()
        for info in traffic_infos:
            if spec.stop_id not in [int(s) for s in info.get("relatedStops") or []]:
                continue
            if line_name not in (info.get("relatedLines") or []):
                continue
            name = info.get("name") or info.get("title") or ""
            if name in seen:
                continue
            seen.add(name)
            time = info.get("time") or {}
            disturbances.append(
                {
                    "title": _clean_title(info.get("title") or ""),
                    "description": (info.get("description") or "").strip(),
                    "start": _to_utc_iso(time.get("start")),
                    "end": _to_utc_iso(time.get("end")),
                    "category": categories.get(info.get("refTrafficInfoCategoryId")),
                }
            )
        result[spec.key] = {
            "available": True,
            "updated": fetched,
            "line": line_name,
            "line_id": spec.line_id,
            "line_type": line.get("type"),
            "line_color": line_color(line_name, line.get("type")),
            "platform": line.get("platform"),
            "api_towards": line.get("towards"),
            "departures": departures,
            "disturbances": disturbances,
        }
    return result
