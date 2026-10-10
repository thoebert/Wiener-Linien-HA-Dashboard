"""Static Wiener Linien open data (lines, stops, routes) for the config flow."""

from __future__ import annotations

import asyncio
import csv
import io
import time
from collections import Counter, defaultdict
from typing import Any

import aiohttp

from .const import OGD_BASE_URL

CATALOG_VERSION = 1
MAX_AGE = 14 * 24 * 3600

_FILES = {
    "lines": "wienerlinien-ogd-linien.csv",
    "stops": "wienerlinien-ogd-haltepunkte.csv",
    "routes": "wienerlinien-ogd-fahrwegverlaeufe.csv",
}

TYPE_LABELS = {
    "en": {
        "ptMetro": "Metro",
        "ptTram": "Tram",
        "ptTramWLB": "Badner Bahn",
        "ptBusCity": "Bus",
        "ptBusNight": "Night bus",
        "ptRufBus": "On-demand bus",
        "ptTrainS": "S-Bahn",
    },
    "de": {
        "ptMetro": "U-Bahn",
        "ptTram": "Straßenbahn",
        "ptTramWLB": "Badner Bahn",
        "ptBusCity": "Bus",
        "ptBusNight": "Nightline",
        "ptRufBus": "Rufbus",
        "ptTrainS": "S-Bahn",
    },
}


class CatalogError(Exception):
    """Catalog could not be downloaded or parsed."""


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=";"))


def build_catalog(lines_csv: str, stops_csv: str, routes_csv: str) -> dict[str, Any]:
    """Build a compact JSON-able catalog from the three CSV files."""
    lines: dict[str, list] = {}
    for row in _rows(lines_csv):
        try:
            sort = int(row.get("SortingHelp") or 0)
        except ValueError:
            sort = 0
        lines[row["LineID"]] = [row["LineText"], row["MeansOfTransport"], sort]

    stops = {row["StopID"]: row["StopText"] for row in _rows(stops_csv)}

    # pattern -> (line, direction, [(seq, stop)])
    patterns: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _rows(routes_csv):
        key = (row["LineID"], row["PatternID"])
        pat = patterns.setdefault(key, {"dir": row["Direction"], "stops": []})
        pat["stops"].append((int(row["StopSeqCount"]), row["StopID"]))

    # line -> stop -> Counter[(direction, terminal)]
    counters: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for (line_id, _pattern), pat in patterns.items():
        ordered = sorted(pat["stops"])
        terminal = ordered[-1][1]
        for _seq, stop_id in ordered:
            counters[line_id][stop_id][(pat["dir"], terminal)] += 1

    line_stops: dict[str, dict[str, list]] = {}
    for line_id, by_stop in counters.items():
        line_stops[line_id] = {
            stop_id: [[d, t, n] for (d, t), n in counter.most_common()]
            for stop_id, counter in by_stop.items()
        }
    return {
        "version": CATALOG_VERSION,
        "fetched": time.time(),
        "lines": lines,
        "stops": stops,
        "line_stops": line_stops,
    }


async def download_catalog(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Download the CSVs and build the catalog."""
    texts: dict[str, str] = {}
    try:
        for name, filename in _FILES.items():
            async with session.get(
                OGD_BASE_URL + filename, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                resp.raise_for_status()
                texts[name] = await resp.text(encoding="utf-8")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CatalogError(str(err)) from err
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, build_catalog, texts["lines"], texts["stops"], texts["routes"]
        )
    except (KeyError, ValueError, IndexError) as err:
        raise CatalogError(f"unexpected CSV format: {err}") from err


def is_fresh(catalog: dict[str, Any] | None) -> bool:
    """Whether a cached catalog is recent and of the current format."""
    return bool(
        catalog
        and catalog.get("version") == CATALOG_VERSION
        and time.time() - catalog.get("fetched", 0) < MAX_AGE
    )


# --- queries used by the config flow -----------------------------------------


def line_options(catalog: dict[str, Any], language: str) -> list[tuple[str, str]]:
    """(line_id, label) for all lines that have route data, sorted naturally."""
    labels = TYPE_LABELS.get(language, TYPE_LABELS["en"])
    items = []
    for line_id in catalog["line_stops"]:
        info = catalog["lines"].get(line_id)
        if not info:
            continue
        name, mode, sort = info
        items.append((sort, name, line_id, f"{name} ({labels.get(mode, mode)})"))
    items.sort()
    return [(line_id, label) for _s, _n, line_id, label in items]


def stop_name_options(catalog: dict[str, Any], line_id: str) -> list[str]:
    """Unique, sorted stop names served by a line."""
    names = {
        catalog["stops"][stop_id]
        for stop_id in catalog["line_stops"].get(line_id, {})
        if stop_id in catalog["stops"]
    }
    return sorted(names, key=str.casefold)


def direction_options(
    catalog: dict[str, Any], line_id: str, stop_name: str
) -> list[dict[str, Any]]:
    """Possible (rbl, destination) pairs for a stop name on a line."""
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for stop_id, routes in catalog["line_stops"].get(line_id, {}).items():
        if catalog["stops"].get(stop_id) != stop_name:
            continue
        for direction, terminal, count in routes:
            terminal_name = catalog["stops"].get(terminal, terminal)
            entry = result.setdefault(
                (stop_id, terminal_name),
                {
                    "stop_id": int(stop_id),
                    "towards": terminal_name,
                    "direction": direction,
                    "count": 0,
                },
            )
            entry["count"] += count
    return sorted(result.values(), key=lambda e: (-e["count"], e["towards"], e["stop_id"]))
