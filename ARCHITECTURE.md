# Architecture

This document explains how the `wiener_linien` integration and its card work and why they are built the way they are. For usage see the [Readme](Readme.md) and the [configuration reference](CONFIGURATION.md); for working on the project see [DEVELOPMENT.md](DEVELOPMENT.md).

## Overview

```
 Home Assistant frontend (browser / app)                 Home Assistant core
┌─────────────────────────────────────┐        ┌──────────────────────────────────────────────┐
│ wiener-linien-card (web component)  │        │ integration `wiener_linien`                  │
│                                     │  ws    │                                              │
│  - renders sensor state/attributes  │◄──────►│  SubscriptionHub  (hass.data, open cards)    │
│  - subscribeMessage(                │ subscr.│        │ who watches which sensor?           │
│      "wiener_linien/subscribe")     │        │        ▼                                     │
│  - details popup                    │        │  WienerLinienManager (poll loop)             │
│                                     │ states │        │ 1 request for all watched stops     │
│  reads hass.states[sensor] ◄────────┼────────┤        ▼                                     │
└─────────────────────────────────────┘        │  api.py ──► wienerlinien.at/ogd_realtime     │
                                               │        │ parse                               │
                                               │        ▼                                     │
                                               │  sensor.py  (1 sensor per monitor)           │
                                               │                                              │
                                               │  config_flow.py + catalog.py                 │
                                               │   └─► open-data CSVs (lines, stops, routes)  │
                                               └──────────────────────────────────────────────┘
```

Data flows **API → manager → sensors → frontend state**. The frontend never talks to the Wiener Linien API; it only tells Home Assistant that it is watching.

## Repository layout

```
custom_components/wiener_linien/
  __init__.py       setup: serves the card, registers websocket command, creates the hub
  manifest.json     metadata (domain, version, single_config_entry)
  const.py          constants (intervals, config keys)
  api.py            API client + parser. Pure Python, no Home Assistant imports
  catalog.py        open-data catalog (lines/stops/routes) + dropdown queries. Pure Python
  manager.py        SubscriptionHub + WienerLinienManager (the polling loop)
  websocket.py      `wiener_linien/subscribe` command
  config_flow.py    config entry, monitor subentries, options (update interval)
  sensor.py         the sensor entity
  strings.json, translations/{en,de}.json
  brand/icon.png, icon@2x.png  integration icon (HA 2026.3+ serves local `brand/` images; logo and dark variants fall back to the icon)
  www/wiener-linien-card.js   the card and its visual editor (no dependencies, no build step)
docs/images/        screenshots for the Readme
```

`api.py` and `catalog.py` deliberately do not import Home Assistant, so they can be tested with plain Python and a real HTTP session.

## Configuration model

- One **config entry** (`single_config_entry`) – it only holds options (`update_interval`).
- Every departure monitor is a **config subentry** of type `monitor`. Subentries can be added, reconfigured and deleted in the UI without touching the entry. Adding or changing one reloads the entry (update listener).
- Subentry data: `stop_id` (RBL), `line_id`, `line` (name), `stop_name`, `towards` (destination filter).
- Subentry `unique_id` = `<stop_id>_<line_id>_<normalized destination>`, which prevents duplicates.
- The sensor's `unique_id` is the **subentry id**. The websocket layer and the manager use this to map an entity id to a monitor.

### Why RBL = direction

In the Wiener Linien data every *platform* has its own stop ID (the *RBL* number), and a platform serves exactly one direction of a line. That is why the setup flow goes *line → stop → destination*: the destination decides the RBL. The `towards` text is only used to **highlight** vehicles that go elsewhere (short runs), it does not filter by itself.

### The setup flow (catalog)

`catalog.py` downloads three CSV files from the Wiener Linien open-data site:

| File | Used for |
|---|---|
| `wienerlinien-ogd-linien.csv` | line id, name, type (sorting and labels) |
| `wienerlinien-ogd-haltepunkte.csv` | stop id (= RBL) → stop name |
| `wienerlinien-ogd-fahrwegverlaeufe.csv` | per line, direction and route pattern the ordered list of stops |

From the routes it builds, for each line and stop, the possible destinations (terminal stop of each route pattern that passes the stop, with a pattern count for ordering). The result (~1 MB) is cached in Home Assistant's `Store` (`.storage/wiener_linien_catalog`) and refreshed after 14 days. If it cannot be downloaded the flow falls back to manual IDs.

Manual setup validates the IDs against the live API (`monitor?stopId=…`) and reads stop and line names from the response.

## Polling lifecycle

Polling is **driven by viewers**:

1. A card calls `connection.subscribeMessage({type: "wiener_linien/subscribe", entity_ids: [...]})`.
2. `websocket.py` registers the subscription in the **SubscriptionHub** (`hass.data[DOMAIN]`) and ties its removal to the websocket connection (`connection.subscriptions[id]`). When the page closes or the connection drops, Home Assistant removes it – no timeouts, no bookkeeping.
3. The hub pokes the **WienerLinienManager**, which runs a background task:
   - fetches immediately when a monitor appears that has not been fetched yet,
   - otherwise every `update_interval` seconds (≥ 15 s), with a lower bound of 5 s between two requests,
   - collects *all* watched stops into **one** API request,
   - after the last subscription is gone it keeps polling for a 60 s grace period (avoids flapping on page changes), then clears the data (sensors become `unknown`) and the task ends.
4. After each fetch the manager signals the sensors via the dispatcher; each sensor writes its state.

The hub lives in `hass.data`, not in the manager, so open cards keep their subscription when the config entry reloads (e.g. after adding a monitor). The reloaded manager attaches to the hub and resumes.

### Rate limit

The API allows roughly 10 requests per 30 s. One request for all stops every ≥ 15 s is at most 2 requests per 30 s, no matter how many cards or devices are open.

## Data model

One sensor per monitor, `device_class: timestamp`, state = next departure (real time if available, otherwise planned). Attributes:

```jsonc
{
  "stop_id": 391, "stop_name": "Nordbahnstraße", "towards": "Praterstern S U",
  "line": "5", "line_id": 105, "line_type": "ptTram", "line_color": "#c00a09",
  "platform": "2", "update_interval": 30, "updated": "2026-10-09T21:08:15Z",
  "departures": [
    {"planned": "...Z", "real": "...Z" /* or null */, "realtime": true,
     "towards": "Praterstern S U", "deviates": false,
     "traffic_jam": false, "barrier_free": true}
  ],
  "disturbances": [
    {"title": "...", "description": "...", "start": "...Z", "end": "...Z", "category": "stoerungkurz"}
  ]
}
```

- All timestamps are converted to proper UTC ISO strings on the server (the API sends `+0200` without a colon, which browsers parse unreliably).
- `realtime` means the API sent a real-time value for that trip. A trip that is only *scheduled* is shown underlined.
- `deviates` is computed with a normalized prefix comparison between the monitor's `towards` and the vehicle's destination.
- Departures and disturbances are **attributes** because the state is limited to 255 characters. They are excluded from the recorder (`_unrecorded_attributes`).
- A disturbance belongs to a monitor if its `relatedStops` contains the RBL **and** `relatedLines` contains the line.

## The card

`www/wiener-linien-card.js` is a dependency-free custom element (no Lit, no build step, no CDN) with a visual editor built on `ha-form`.

- **Rendering:** reads `hass.states[entity]`; minutes are computed in the browser from the timestamps and refreshed every 15 s, so the numbers keep counting down between fetches.
- **Freshness:** data older than ~2.5 update intervals is not shown (`…`), because with viewer-driven polling stale data is possible (e.g. right after opening).
- **Subscription:** subscribes while connected and the page is visible, unsubscribes otherwise; on failure retries with growing pauses.
- **Layout:** the host is one grid row high (`getGridOptions`) and 100 % height, so it matches tile cards; line badges are square (`min-width = height`).
- **Popup:** appended to `document.body` with its own shadow root (immune to ancestor `transform`/`contain` that would break `position: fixed`). All API text is inserted via `textContent`, never HTML.
- **Registration gotcha:** Home Assistant replaces the global `customElements` registry with a scoped-registry polyfill while it boots, and extra modules execute before that. Elements defined too early are lost (*"Custom element doesn't exist"*). The card therefore waits until `customElements.get("home-assistant")` exists before defining anything.
- **Delivery:** the integration serves the card from its own HTTP view with `Cache-Control: no-cache` (plus ETag), so browsers and the app pick up a new version on the next load, and registers it with `frontend.add_extra_js_url` – no Lovelace resource needed.

## Design decisions

| Decision | Reason |
|---|---|
| Integration instead of Node-RED + `input_text` | Nothing to install besides Home Assistant; a state can hold only 255 characters, attributes can hold the full data |
| Websocket subscription instead of the old `fire_event` | Firing events over the websocket requires **admin** rights. A non-admin user (e.g. a wall tablet) never registered as a viewer and saw no data. Subscriptions work for every user and are cleaned up automatically |
| Poll only while watched | Saves API requests and server load. Trade-off: sensors are `unknown` while no card is visible, so they are not suitable for automations running in the background. A "keep polling" option or a time window can be added if needed |
| One request for all stops | Keeps the rate limit a non-issue regardless of the number of cards |
| Config subentries | Each monitor can be added or removed individually in the UI |
| Destination as dropdown | A destination identifies direction and RBL in one choice; no ID lookup necessary |
| Vanilla web component | No dependency on CDNs or Home Assistant's internal Lit version; works on old tablets |

## Testing

There is no automated test suite yet; the integration was verified against a real Home Assistant instance:

- `api.py` / `catalog.py`: run directly in the Home Assistant container against the live API (catalog build, parser output for several stops, error codes).
- Config flow: driven through the config-subentry flow API (search path, manual path, unknown stop, wrong line, duplicate, reconfigure, options validation).
- Polling lifecycle: card open → data and subscription; page closed → sensors `unknown` after ~60 s; reconfigure while a card is open → data keeps flowing.
- Frontend: a test dashboard in a real browser (rendering, row height compared with tile cards, popup, visual editor in the card picker, first load without cache). The popup/card logic can also be exercised in isolation with a mock `hass` object.

Ideas for proper tests: `pytest-homeassistant-custom-component` for the flow and manager, recorded API responses as fixtures for `api.py`.

## Possible extensions

- Optional "keep polling" mode or time window for use in automations
- Show elevator notices (`aufzugsinfo`) or per-line notices
- Several departure rows per card (one station, multiple lines)
- Automated tests and CI (hassfest, HACS validation)
