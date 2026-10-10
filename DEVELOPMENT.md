# Development

Notes for working on the project. For how it works see [ARCHITECTURE.md](ARCHITECTURE.md), for user-facing settings [CONFIGURATION.md](CONFIGURATION.md).

## Set-up

The integration needs nothing to build: Python files plus one dependency-free JavaScript file.

```
custom_components/wiener_linien/    the integration (copy this folder into a Home Assistant config)
  www/wiener-linien-card.js         the card – edit and reload the browser
docs/images/                        screenshots used in the Readme
```

Requirements: Home Assistant 2025.3+ (config subentries), developed against 2026.9 / Python 3.14.

## Deploy to a test instance

1. Copy the folder to the instance:
   ```bash
   rsync -a --exclude __pycache__ custom_components/wiener_linien/ \
     <host>:<config>/custom_components/wiener_linien/
   ```
2. **Python or manifest changes:** restart Home Assistant.
   **Only `wiener-linien-card.js`:** reload the browser. The card is served with `Cache-Control: no-cache`; if a tab still shows the old version, reload with *Disable cache*.
3. After a restart the integration needs a moment to load. Cards retry their subscription automatically.

## Testing

There is no automated test suite yet (see ideas in [ARCHITECTURE.md](ARCHITECTURE.md#testing)). Useful manual checks:

- **API client and catalog** (`api.py`, `catalog.py` do not import Home Assistant) – run them in the Home Assistant container or any Python with `aiohttp`: build the catalog, fetch and parse a few stops, check the unknown-stop error.
- **Config flow** – add monitors through *Add departure monitor* (search and manual path), also the error cases: unknown stop, wrong line, duplicate, and *Reconfigure*.
- **Polling lifecycle** – open a card: sensors get data within seconds. Close the page: the sensors turn `unknown` after about a minute. Change a monitor while a card is open: the card must keep updating.
- **Card** – first page load without cache (the card must be defined on a cold start), row height next to a `tile` card, popup, the visual editor in the card picker.

## Card demo mode

For testing states the live API does not currently show (an active disruption, many departures, a specific line), the card has a `demo` option. It renders fixed example data instead of a sensor – no entity, no subscription, no API requests.

```yaml
type: custom:wiener-linien-card
title: Dornbach
demo:
  line: "2"                    # text in the line badge
  towards: Dornbach            # destination of the vehicles
  line_color: "#c00a09"        # badge colour
  departures: [10, 13]         # minutes from now
  scheduled: [1]               # indexes of departures without live data (underlined)
  jam: [0]                     # indexes of departures stuck in a traffic jam
  disturbances:                # notices, shown on the card and in the popup
    - title: Gleisschaden
      description: Full text shown in the popup
      category: stoerunglang   # or stoerungkurz
      start: "2026-10-10T05:30:00Z"
      end: "2026-10-10T16:00:00Z"
```

The minutes count down from the moment the page is loaded. The option is not part of the visual editor on purpose.


## Gotchas worth knowing

- **Custom element registration.** Home Assistant swaps the `customElements` registry while it boots. The card defines its elements only after `home-assistant` exists, otherwise a cold start shows "Custom element doesn't exist". Do not move the `define` calls to the top level of the module.
- **Websocket rights.** Firing events from the frontend needs admin rights; the subscription command does not. Keep the card's "I'm watching" signal on subscriptions.
- **Entry reloads.** Subscriptions live in the `SubscriptionHub` in `hass.data` so they survive a reload of the config entry. Do not store them on the manager.
- **Manual setup and the night.** Manual IDs are validated against live departures, so they cannot be added while a line is not running.

## Releasing

1. Bump `version` in `custom_components/wiener_linien/manifest.json`.
2. Update the docs if behaviour changed.
3. Tag the release on GitHub; HACS picks it up.
