# Configuration reference

All settings, from the everyday options in the UI to the advanced YAML options at the bottom. For a quick start see the [Readme](Readme.md).

## Departure monitors

A monitor is one line at one stop in one direction. Each monitor becomes one sensor in Home Assistant. Add them under *Settings → Devices & services → Wiener Linien → Add departure monitor*.

### Search by line and stop (recommended)

1. Choose the **line** (`5`, `U2`, `2A`, …)
2. Choose the **stop**
3. Choose the **destination**. This also selects the right platform: every direction has its own stop ID (RBL). Vehicles that go somewhere *else* than the chosen destination are highlighted on the card.

The lists come from the official Wiener Linien open data. They are downloaded once and refreshed every two weeks.

### Enter IDs manually

Use this if the lists cannot be loaded or a line is missing:

| Field | Meaning |
|---|---|
| Stop ID (RBL) | Platform number, e.g. `391` |
| Line ID | Optional. Numeric line id, e.g. `105` for line 5. Only needed if several lines stop at that RBL |
| Destination filter | Optional. Vehicles whose destination does not start with this text are highlighted. Leave empty to turn it off |

IDs can be looked up with the [mabe.at helper](https://till.mabe.at/rbl/) (shown as *RBL/StopID*, the line id is `line=` in the URL) or in the [open data](https://www.data.gv.at/katalog/dataset/wiener-linien-echtzeitdaten-via-datendrehscheibe-wien).

The same station (e.g. Praterstern) has a different stop ID for each line and direction. Manual setup checks the IDs against the live data, so it can fail at night when a line is not running.

### Change a monitor later

*Reconfigure* (⋮ next to the monitor) changes the destination filter. Delete a monitor from the same menu.

## Update interval

*Settings → Devices & services → Wiener Linien → Configure.*

| Setting | Default | Range |
|---|---|---|
| Update interval | 30 seconds | 15 – 300 seconds |

The API allows roughly 10 requests per 30 seconds. All monitors are fetched with a single request, so even 15 seconds leaves plenty of headroom, no matter how many cards or devices show departures.

## The card

Add it with *Edit dashboard → Add card → Wiener Linien Departures*. The visual editor offers:

| Setting | Description |
|---|---|
| Departure sensor | One of the configured monitors |
| Title | Text next to the line badge. Default: the destination of the monitor |
| Line label | Text in the line badge. Default: the line of the monitor |
| Visible departures | How many departure bubbles are shown |
| Card width | Width in grid columns (sections view) |
| Line colour | Automatic by line type, or a custom colour |

Click anywhere on a card to open the details: full text of all notices with validity period, plus all upcoming departures.

### Reading the card

- A number is the minutes until departure, a `*` means *departing now*.
- An **underlined** number has no live data yet – the time is from the timetable. Hover over it for a short explanation.
- `1. → Aspernstraße` means: the first vehicle is heading to a different destination than usual. `Stau` / `Traffic jam` marks a vehicle stuck in a traffic jam.
- Cards show `…` instead of minutes when no recent data is available (for example in the first moments after opening a dashboard).

### Line colours

| Mode | Colour | Hex |
|---|---|---|
| Bus | ![#0b295d](https://placehold.co/15x15/0b295d/0b295d.png) | `#0b295d` |
| Tram | ![#c00a09](https://placehold.co/15x15/c00a09/c00a09.png) | `#c00a09` |
| S-Bahn | ![#0089c4](https://placehold.co/15x15/0089c4/0089c4.png) | `#0089c4` |
| Regional train | ![#e2002a](https://placehold.co/15x15/e2002a/e2002a.png) | `#e2002a` |
| U1 | ![#e3000f](https://placehold.co/15x15/e3000f/e3000f.png) | `#e3000f` |
| U2 | ![#a862a4](https://placehold.co/15x15/a862a4/a862a4.png) | `#a862a4` |
| U3 | ![#db7607](https://placehold.co/15x15/db7607/db7607.png) | `#db7607` |
| U4 | ![#01963e](https://placehold.co/15x15/01963e/01963e.png) | `#01963e` |
| U5 | ![#008f95](https://placehold.co/15x15/008f95/008f95.png) | `#008f95` |
| U6 | ![#9d6830](https://placehold.co/15x15/9d6830/9d6830.png) | `#9d6830` |

## How data is loaded

- Departures are only fetched while at least one card is visible. Without an open dashboard the sensors show `unknown`; polling stops about a minute after the last card is gone.
- When a card appears (or a hidden tab becomes visible again) data is fetched immediately.

Because of this the sensors are not meant for automations that must run while no dashboard is open. See [ARCHITECTURE.md](ARCHITECTURE.md#design-decisions) for the reasoning.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Card shows `…` | No data yet (first seconds after opening, or the integration is still starting after a restart), or the API cannot be reached. Look for `wiener_linien` in *Settings → System → Logs* |
| "Custom element doesn't exist" after an update | Reload the page. In the companion app clear the frontend cache (*Settings → Companion app → Troubleshooting*) |
| A monitor cannot be added manually | The API returns no departures for that stop right now (night, line not running). Try again during service hours |
| The wrong vehicles are highlighted | *Reconfigure* the monitor and change the destination filter |
| A destination or stop is missing in the lists | Use *Enter IDs manually* |

## Sensors (for templates and automations)

Each monitor creates one sensor with device class `timestamp`. Its **state** is the time of the next departure. The rest is in attributes:

| Attribute | Content |
|---|---|
| `departures` | list of `{planned, real, realtime, towards, deviates, traffic_jam, barrier_free}` (UTC ISO timestamps) |
| `disturbances` | list of `{title, description, start, end, category}` |
| `line`, `line_id`, `line_type`, `line_color` | line information, colour by line type |
| `stop_id`, `stop_name`, `towards`, `platform` | location and configured destination |
| `updated`, `update_interval` | time of the last fetch (UTC) and the configured interval |

The attributes are excluded from the recorder and do not grow the database.

## Advanced: YAML configuration

The card can be configured in the dashboard's YAML (*Show code editor*) as well:

```yaml
type: custom:wiener-linien-card
entity: sensor.5_nordbahnstrasse_westbahnhof_s_u
title: Westbahnhof        # optional, default: destination of the monitor
line: "5"                 # optional, default: line of the monitor
color: "#c00a09"          # optional, default: automatic by line type
max_departures: 2         # optional, 1-10, default 2
column_width: 6           # optional, 6-12, default 6 (sections view)
```

| Option | Type | Default | Description |
|---|---|---|---|
| `entity` | string | – | **Required.** A sensor of this integration |
| `title` | string | destination of the monitor | Text next to the line badge |
| `line` | string | line of the monitor | Text in the line badge |
| `color` | string | by line type | Badge colour, any CSS colour value |
| `max_departures` | integer | `2` | Number of visible departure bubbles |
| `column_width` | integer | `6` | Width in grid columns, sections view |

Place cards next to each other by giving them a width of `6` in a sections view (two per row) or make one span the full row with `12`.
