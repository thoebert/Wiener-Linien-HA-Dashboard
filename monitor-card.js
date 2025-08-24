import { html, LitElement } from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";


class MonitorCard extends LitElement {
  constructor() {
    super();
    this.createCardId();
  }

  createCardId(){
    if (this.watcherId != null) return;
    this.watcherId = Math.floor(Math.random() * 10000);
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.publish_visibility) {
      this._handleVisibilityChange();
      document.addEventListener("visibilitychange", this._handleVisibilityChange.bind(this));
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this.publish_visibility) {
      this._handleVisibilityChange();
      document.removeEventListener("visibilitychange", this._handleVisibilityChange.bind(this));
    }
  }

  _handleVisibilityChange() {
    const eventType = document.hidden ? "remove_watcher" : "add_watcher";
    this.hass.connection.sendMessage({
      type: "fire_event",
      event_type: "dashboard_watcher_changed",
      event_data: {
        watcherId: this.watcherId,
        action: eventType,
      },
    });
  }

  get publish_visibility() {
    return this._config.publish_visibility || false;
  }

  static get properties() {
    return {
      hass: {},
      _config: {},
    };
  }

  setConfig(config) {
    this._config = config;

  }

  // The height of your card. Home Assistant uses this to automatically
  // distribute all cards over the available columns in masonry view
  getCardSize() {
    return 1;
  }

  // The rules for sizing your card in the grid in sections view
  getGridOptions() {
    return {
      rows: 1,
      columns: 6,
      min_columns: 6,
      min_rows: 1,
      max_rows: 1,
    };
  }

  render() {
    if (!this.hass || !this._config) {
      return html``;
    }
    const maxDepartures = this._config.max_departures || 2;
    const title = this._config.title || "";
    const line = this._config.line || " ";
    const stateObj = this.hass.states[this._config.entity];
    const color = this._config.color || "#e30014";
    var data = {
      d: [],
      r: [],
    }
    if (stateObj !== null && stateObj.state !== "unknown") {
      if (stateObj.state != '') {
        data = JSON.parse(stateObj.state);
      }
    }
    data.d = data.d.slice(0, Math.min(maxDepartures, data.d.length));

    return html`
      <style>
        .content {
          padding: 10px;
          padding-bottom: 8px;
          flex-direction: row;
          flex: 1;
          gap: 3px;
          display: flex;
          height: 100%;
        }
        .timebg {
          margin-top: auto;
          margin-bottom: auto;
          background-color: color-mix(in srgb, var(--grey-color) 20%, transparent);
          border-radius: 10px;
          text-align: center;
        }
        .timebg-inactive {
          text-decoration: underline;
        }
        .timebg-hidden {
          display: none;
        }
        .time {
          font-weight: 500;
          font-size: 16px;
          line-height: 30px;
          width: 30px;
          height: 30px;
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
          min-width: 18pt;
          line-height: 18pt;
          text-align: center;
          background-color: ${color};
          color: #ffffff;
          margin-right: 6px;
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
        }
      </style>
      <ha-card class="content">
        <div class="info">
          <div class="primary">
            <div class="line">${line}</div>
            <span class="title">${title}</span>
          </div>
          ${data.t
            ? html`<div class="secondary">
                    <span class="title">${data.t}</span>
                  </div>`
            : ""}
        </div>
        ${data.d.map((d, i) => html`
          <div class="timebg ${d>=0 ? "" : "timebg-hidden"} ${data.r[i]==1 ? "" : "timebg-inactive"}">
            <div class="time">${d == 0 ? "*" : d}</div>
          </div>
        `)}
      </ha-card>
    `;
  }
}

customElements.define("monitor-card", MonitorCard);