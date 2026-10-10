/*
 * Wiener Linien departure card (dependency-free web component).
 *
 * Reads a `sensor.*` entity of the `wiener_linien` integration and, while it is
 * on screen, keeps a websocket subscription open so the integration polls the
 * Wiener Linien API. Without any open card nothing is fetched.
 */

const CARD_VERSION = "2.0.0";
const MIN_STALE_AFTER_MS = 45 * 1000;

const STRINGS = {
  en: {
    jam: "Traffic jam",
    scheduledHint: "Timetable time – no live data available yet",
    notices: "Notices",
    departures: "Departures",
    inMin: (m) => (m <= 0 ? "now" : `in ${m} min`),
    until: "until",
    since: "since",
    noData: "No data",
    close: "Close",
    stoerungkurz: "Short-term change",
    stoerunglang: "Disruption",
    noDepartures: "No upcoming departures",
    // editor
    entity: "Departure sensor",
    title: "Title (default: destination)",
    line: "Line label (default: from sensor)",
    max_departures: "Visible departures",
    column_width: "Card width (columns)",
    color: "Line colour",
    auto: "Automatic",
    autoHint: "Automatic (from line type)",
  },
  de: {
    jam: "Stau",
    scheduledHint: "Fahrplanzeit – noch keine Echtzeitdaten verfügbar",
    notices: "Meldungen",
    departures: "Abfahrten",
    inMin: (m) => (m <= 0 ? "jetzt" : `in ${m} min`),
    until: "bis",
    since: "seit",
    noData: "Keine Daten",
    close: "Schließen",
    stoerungkurz: "Kurzfristige Änderung",
    stoerunglang: "Störung",
    noDepartures: "Keine Abfahrten",
    entity: "Abfahrts-Sensor",
    title: "Titel (Standard: Ziel)",
    line: "Linienbezeichnung (Standard: vom Sensor)",
    max_departures: "Sichtbare Abfahrten",
    column_width: "Kartenbreite (Spalten)",
    color: "Linienfarbe",
    auto: "Automatisch",
    autoHint: "Automatisch (nach Linientyp)",
  },
};

const strings = (hass) =>
  STRINGS[(hass && hass.language ? hass.language : "en").slice(0, 2)] || STRINGS.en;

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
  }
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

const CARD_STYLE = `
  :host { display: block; height: 100%; }
  ha-card.content {
    cursor: pointer;
    padding: 10px;
    padding-bottom: 8px;
    flex-direction: row;
    flex: 1;
    gap: 3px;
    display: flex;
    height: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }
  .timebg {
    margin-top: auto;
    margin-bottom: auto;
    background-color: color-mix(in srgb, var(--secondary-text-color, #888) 20%, transparent);
    border-radius: 10px;
    text-align: center;
  }
  .timebg.scheduled { text-decoration: underline; }
  .timebg.dim { opacity: 0.5; }
  .time {
    font-weight: 500;
    font-size: 16px;
    line-height: 30px;
    min-width: 30px;
    height: 30px;
    padding: 0 2px;
  }
  .info {
    min-width: 0;
    margin-right: auto;
    margin-top: auto;
    margin-bottom: auto;
  }
  .primary {
    display: flex;
    font-weight: 500;
    font-size: 14px;
    line-height: 16px;
    letter-spacing: .1px;
    margin-right: 3px;
  }
  .line {
    box-sizing: border-box;
    flex-shrink: 0;
    min-width: 18pt;
    height: 18pt;
    line-height: 18pt;
    text-align: center;
    color: #ffffff;
    margin-right: 6px;
    padding: 0 3px;
  }
  .title {
    margin-top: auto;
    margin-bottom: auto;
    text-overflow: ellipsis;
    overflow: hidden;
    white-space: nowrap;
    width: 100%;
  }
  .secondary {
    margin-top: 3px;
    font-size: 12px;
    line-height: 16px;
    letter-spacing: .4px;
    text-overflow: ellipsis;
    overflow: hidden;
    white-space: nowrap;
    color: var(--secondary-text-color);
  }
`;

class WienerLinienCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._state = undefined;
    this._unsub = null;
    this._subEntity = null;
    this._subscribing = false;
    this._timer = null;
    this._onVisibility = () => this._syncSubscription();
  }

  static getConfigElement() {
    return document.createElement("wiener-linien-card-editor");
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find((id) => {
      const a = hass.states[id].attributes;
      return id.startsWith("sensor.") && a.stop_id !== undefined && "towards" in a;
    });
    return { entity: entity || "", max_departures: 2 };
  }

  setConfig(config) {
    if (!config || (!config.entity && !config.demo)) {
      throw new Error("Please select a Wiener Linien sensor (entity).");
    }
    this._config = { max_departures: 2, column_width: 6, ...config };
    this._demoBase = Date.now();
    this._render();
    this._syncSubscription();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const state = hass.states[this._config.entity];
    if (state !== this._state || (this._config.demo && !this._demoRendered)) {
      this._state = state;
      this._demoRendered = true;
      this._render();
    }
    this._syncSubscription();
  }

  getCardSize() {
    return 1;
  }

  getGridOptions() {
    return {
      rows: 1,
      columns: Number((this._config && this._config.column_width) || 6),
      min_columns: 6,
      min_rows: 1,
      max_rows: 1,
    };
  }

  connectedCallback() {
    document.addEventListener("visibilitychange", this._onVisibility);
    this._timer = setInterval(() => this._render(), 15000);
    this._syncSubscription();
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisibility);
    clearInterval(this._timer);
    clearTimeout(this._retryTimer);
    this._timer = null;
    this._unsubscribe();
  }

  // --- subscription: tells the integration that somebody is watching -----------

  _syncSubscription() {
    const wanted =
      !this._config?.demo &&
      this.isConnected &&
      this._hass &&
      this._hass.connection &&
      this._config &&
      !document.hidden;
    if (!wanted) {
      this._unsubscribe();
      return;
    }
    if (this._unsub && this._subEntity !== this._config.entity) this._unsubscribe();
    if (!this._unsub && !this._subscribing && !this._retryTimerActive()) this._subscribe();
  }

  _retryTimerActive() {
    return this._retryUntil !== undefined && Date.now() < this._retryUntil;
  }

  async _subscribe() {
    this._subscribing = true;
    const entity = this._config.entity;
    let unsub = null;
    try {
      unsub = await this._hass.connection.subscribeMessage(() => {}, {
        type: "wiener_linien/subscribe",
        entity_ids: [entity],
      });
      this._retryDelay = 0;
    } catch (err) {
      // e.g. integration still starting up: retry with growing pauses
      this._retryDelay = Math.min((this._retryDelay || 1000) * 2, 30000);
      clearTimeout(this._retryTimer);
      this._retryUntil = Date.now() + this._retryDelay;
      this._retryTimer = setTimeout(() => this._syncSubscription(), this._retryDelay);
      console.warn(`wiener-linien-card: subscribe failed, retrying in ${this._retryDelay} ms`, err);
    } finally {
      this._subscribing = false;
    }
    if (!unsub) return;
    // The card may have been detached or hidden while the request was in flight.
    if (this.isConnected && !document.hidden && this._config && this._config.entity === entity) {
      this._unsub = unsub;
      this._subEntity = entity;
    } else {
      try {
        Promise.resolve(unsub()).catch(() => {});
      } catch (_err) {
        /* connection already closed */
      }
      this._syncSubscription();
    }
  }

  _unsubscribe() {
    if (!this._unsub) return;
    const unsub = this._unsub;
    this._unsub = null;
    this._subEntity = null;
    try {
      Promise.resolve(unsub()).catch(() => {});
    } catch (_err) {
      /* connection already closed */
    }
  }

  // --- view model ---------------------------------------------------------------

  _model() {
    const cfg = this._config;
    const state = this._hass && this._hass.states[cfg.entity];
    const now = Date.now();
    const attrs = cfg.demo ? this._demoAttributes(cfg.demo, now) : (state && state.attributes) || {};
    const updated = attrs.updated ? Date.parse(attrs.updated) : 0;
    const known = cfg.demo || (state && state.state !== "unknown" && state.state !== "unavailable");
    // data counts as fresh for ~2.5 update intervals (the integration polls only while watched)
    const staleAfter = Math.max(MIN_STALE_AFTER_MS, (Number(attrs.update_interval) || 30) * 2500 + 15000);
    const fresh = !!(known || attrs.available === false) && now - updated < staleAfter;

    const max = Math.max(1, Math.min(10, Number(cfg.max_departures) || 2));
    const all = (attrs.departures || [])
      .map((d) => ({
        t: Date.parse(d.real || d.planned),
        realtime: !!d.realtime,
        towards: d.towards || "",
        deviates: !!d.deviates,
        jam: !!d.traffic_jam,
      }))
      .filter((d) => !Number.isNaN(d.t) && d.t >= now)
      .map((d) => ({ ...d, minutes: Math.floor((d.t - now) / 60000) }));
    const shown = all.slice(0, max);

    const S = strings(this._hass);
    const parts = (attrs.disturbances || []).map((d) => d.title).filter(Boolean);
    shown.forEach((d, i) => {
      const marks = [];
      if (d.jam) marks.push(S.jam);
      if (d.deviates) marks.push(`→ ${d.towards}`);
      if (marks.length) parts.push(`${i + 1}. ${marks.join(", ")}`);
    });

    return {
      fresh,
      all,
      shown,
      summary: fresh ? parts.join(", ") : "",
      disturbances: attrs.disturbances || [],
      title: cfg.title !== undefined && cfg.title !== "" ? cfg.title : attrs.towards || attrs.stop_name || "",
      line: cfg.line !== undefined && cfg.line !== "" ? cfg.line : attrs.line || " ",
      color: cfg.color || attrs.line_color || "#e30014",
    };
  }

  // Static example data for documentation and screenshots (config option `demo`):
  //   demo: { line: "S2", towards: "Meidling", line_color: "#0089c4",
  //           departures: [4, 13, 18], scheduled: [2], jam: [],
  //           disturbances: [{ title: "Gleisschaden", description: "..." }] }
  _demoAttributes(demo, now) {
    const scheduled = new Set(demo.scheduled || []);
    const jam = new Set(demo.jam || []);
    return {
      line: demo.line || "",
      line_color: demo.line_color,
      towards: demo.towards || "",
      updated: new Date(now).toISOString(),
      update_interval: 30,
      departures: (demo.departures || []).map((minutes, i) => {
        const when = new Date(this._demoBase + minutes * 60000 + 30000).toISOString();
        return {
          planned: when,
          real: scheduled.has(i) ? null : when,
          realtime: !scheduled.has(i),
          towards: demo.towards || "",
          deviates: false,
          traffic_jam: jam.has(i),
        };
      }),
      disturbances: demo.disturbances || [],
    };
  }

  // --- rendering --------------------------------------------------------------------

  _render() {
    if (!this._config || !this._hass) return;
    const S = strings(this._hass);
    const m = this._model();
    const root = this.shadowRoot;
    root.replaceChildren();

    const style = document.createElement("style");
    style.textContent = CARD_STYLE;

    const secondary = m.summary ? el("div", { class: "secondary" }, m.summary) : null;

    const bubbles = m.fresh
      ? m.shown.map((d) =>
          el(
            "div",
            { class: `timebg${d.realtime ? "" : " scheduled"}`, ...(d.realtime ? {} : { title: S.scheduledHint }) },
            el("div", { class: "time" }, d.minutes === 0 ? "*" : d.minutes)
          )
        )
      : [el("div", { class: "timebg dim", title: S.noData }, el("div", { class: "time" }, "…"))];

    const card = el(
      "ha-card",
      { class: "content", onclick: () => this._openDetails() },
      el(
        "div",
        { class: "info" },
        el(
          "div",
          { class: "primary" },
          el("div", { class: "line", style: `background-color:${m.color}` }, m.line),
          el("span", { class: "title" }, m.title)
        ),
        secondary
      ),
      ...bubbles
    );
    root.append(style, card);
  }

  // --- details dialog ------------------------------------------------------------------

  _openDetails() {
    const S = strings(this._hass);
    const m = this._model();
    const lang = (this._hass.language || "en").slice(0, 2);
    const format = this._hass.locale && this._hass.locale.time_format;
    const hour12 = format === "12" ? true : format === "24" ? false : undefined;
    const hhmm = (iso) =>
      iso
        ? new Date(iso).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit", hour12 })
        : "";
    const squash = (text) => (text || "").replace(/[\s.:,]+/g, "").toLowerCase();

    const host = document.createElement("div");
    const root = host.attachShadow({ mode: "open" });
    const close = () => {
      document.removeEventListener("keydown", onKey);
      host.remove();
    };
    const onKey = (e) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);

    const style = document.createElement("style");
    style.textContent = `
      .backdrop { position: fixed; inset: 0; z-index: 9999; background: rgba(0,0,0,.5);
        display: flex; align-items: center; justify-content: center; padding: 16px; box-sizing: border-box; }
      .dialog { background: var(--card-background-color, #fff); color: var(--primary-text-color, #000);
        border-radius: var(--ha-card-border-radius, 12px); max-width: 520px; width: 100%;
        max-height: 85vh; overflow: auto; box-shadow: 0 8px 32px rgba(0,0,0,.4);
        font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
      header { display: flex; align-items: center; gap: 8px; padding: 14px 16px; font-weight: 500;
        border-bottom: 1px solid var(--divider-color, #ddd); }
      header .line { box-sizing: border-box; flex-shrink: 0; min-width: 24px; height: 24px; line-height: 24px; text-align: center; color: #fff; padding: 0 3px; }
      header .title { flex: 1; font-size: 16px; }
      button { background: none; border: none; color: var(--primary-text-color); font-size: 20px;
        cursor: pointer; padding: 4px 8px; }
      section { padding: 12px 16px; }
      h3 { margin: 0 0 8px; font-size: 12px; font-weight: 500; text-transform: uppercase;
        letter-spacing: .5px; color: var(--secondary-text-color); }
      .notice { margin-bottom: 12px; }
      .notice b { display: block; margin-bottom: 2px; }
      .notice .meta { font-size: 12px; color: var(--secondary-text-color); margin-bottom: 4px; }
      .notice p { margin: 0; white-space: pre-wrap; font-size: 14px; line-height: 1.4; }
      .dep { display: flex; gap: 8px; padding: 4px 0; font-size: 14px; align-items: baseline; }
      .dep .when { min-width: 74px; font-weight: 500; }
      .dep .clock { min-width: 44px; color: var(--secondary-text-color); }
      .dep .flags { color: var(--secondary-text-color); font-size: 12px; }
      .dep.warn .what { color: var(--warning-color, #ff9800); }
      .dep.scheduled .when, .dep.scheduled .clock { text-decoration: underline; }
    `;

    const notices = m.disturbances.map((d) => {
      const meta = [
        S[d.category] || "",
        d.start ? `${S.since} ${hhmm(d.start)}` : "",
        d.end ? `${S.until} ${hhmm(d.end)}` : "",
      ].filter(Boolean).join(" · ");
      const body = d.description && squash(d.description) !== squash(d.title) ? d.description : "";
      return el("div", { class: "notice" }, el("b", null, d.title), meta && el("div", { class: "meta" }, meta), body && el("p", null, body));
    });

    const deps = m.all.map((d) => {
      const flags = d.jam ? [S.jam] : [];
      return el(
        "div",
        {
          class: `dep${d.deviates || d.jam ? " warn" : ""}${d.realtime ? "" : " scheduled"}`,
          ...(d.realtime ? {} : { title: S.scheduledHint }),
        },
        el("span", { class: "when" }, S.inMin(d.minutes)),
        el("span", { class: "clock" }, hhmm(new Date(d.t).toISOString())),
        el("span", { class: "what" }, d.deviates ? `→ ${d.towards}` : d.towards),
        el("span", { class: "flags" }, flags.join(" · "))
      );
    });

    const dialog = el(
      "div",
      { class: "dialog", onclick: (e) => e.stopPropagation() },
      el(
        "header",
        null,
        el("span", { class: "line", style: `background-color:${m.color}` }, m.line),
        el("span", { class: "title" }, m.title),
        el("button", { title: S.close, onclick: close }, "✕")
      ),
      notices.length ? el("section", null, el("h3", null, S.notices), ...notices) : null,
      el(
        "section",
        null,
        el("h3", null, S.departures),
        ...(deps.length ? deps : [m.fresh ? S.noDepartures : S.noData])
      )
    );
    root.append(style, el("div", { class: "backdrop", onclick: close }, dialog));
    document.body.append(host);
  }
}

class WienerLinienCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._built = false;
  }

  setConfig(config) {
    this._config = config;
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _schema(S) {
    return [
      { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "wiener_linien" } } },
      { name: "title", selector: { text: {} } },
      { name: "line", selector: { text: {} } },
      { name: "max_departures", selector: { number: { min: 1, max: 7, step: 1, mode: "slider" } } },
      { name: "column_width", selector: { number: { min: 6, max: 12, step: 1, mode: "slider" } } },
    ];
  }

  _build() {
    this._built = true;
    const style = document.createElement("style");
    style.textContent = `
      .color { display: flex; align-items: center; gap: 12px; margin-top: 16px; color: var(--primary-text-color); }
      .color label { flex: 1; }
      .color input { width: 48px; height: 32px; padding: 0; border: none; background: none; cursor: pointer; }
      .color .hint { font-size: 12px; color: var(--secondary-text-color); }
      .color button { cursor: pointer; }
    `;
    this._form = document.createElement("ha-form");
    this._form.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const next = { ...this._config, ...ev.detail.value };
      for (const key of ["title", "line"]) {
        if (next[key] === "" || next[key] === undefined) delete next[key];
      }
      this._emit(next);
    });
    this._colorLabel = el("label");
    this._colorHint = el("span", { class: "hint" });
    this._colorInput = el("input", { type: "color" });
    this._colorInput.addEventListener("change", () => this._emit({ ...this._config, color: this._colorInput.value }));
    this._autoButton = el("button", { type: "button" });
    this._autoButton.addEventListener("click", () => {
      const next = { ...this._config };
      delete next.color;
      this._emit(next);
    });
    const row = el("div", { class: "color" }, this._colorLabel, this._colorHint, this._colorInput, this._autoButton);
    this.shadowRoot.append(style, this._form, row);
  }

  _emit(config) {
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true })
    );
    this._update();
  }

  _update() {
    if (!this._hass) return;
    if (!this._built) this._build();
    const S = strings(this._hass);
    this._form.hass = this._hass;
    this._form.schema = this._schema(S);
    this._form.data = { max_departures: 2, column_width: 6, ...this._config };
    this._form.computeLabel = (item) => S[item.name] || item.name;

    const state = this._hass.states[this._config.entity];
    const auto = (state && state.attributes.line_color) || "#e30014";
    const custom = /^#[0-9a-f]{6}$/i.test(this._config.color || "") ? this._config.color : null;
    this._colorLabel.textContent = S.color;
    this._colorInput.value = custom || (/^#[0-9a-f]{6}$/i.test(auto) ? auto : "#e30014");
    this._colorHint.textContent = this._config.color ? "" : S.autoHint;
    this._autoButton.textContent = S.auto;
    this._autoButton.disabled = !this._config.color;
  }
}

// HA replaces the global customElements registry (scoped-registry polyfill)
// while it boots. Elements defined before that are lost, and extra modules are
// executed very early. So wait until the frontend itself is registered.
function whenFrontendReady(callback) {
  const check = () =>
    customElements.get("home-assistant") ? callback() : setTimeout(check, 50);
  check();
}

whenFrontendReady(() => {
  if (!customElements.get("wiener-linien-card")) {
    customElements.define("wiener-linien-card", WienerLinienCard);
  }
  if (!customElements.get("wiener-linien-card-editor")) {
    customElements.define("wiener-linien-card-editor", WienerLinienCardEditor);
  }
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "wiener-linien-card")) {
    window.customCards.push({
      type: "wiener-linien-card",
      name: "Wiener Linien Departures",
      description: "Real-time departures for one Wiener Linien line and stop.",
      preview: false,
    });
  }
});

console.info(`%c WIENER-LINIEN-CARD %c ${CARD_VERSION} `, "color:#fff;background:#c00a09", "");
