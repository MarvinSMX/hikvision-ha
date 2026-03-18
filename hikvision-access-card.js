/**
 * Hikvision Access Card
 * Lovelace custom card für Hikvision Face Terminals.
 *
 * Installation via HACS:
 *   Repository als "Frontend" in HACS hinzufügen.
 *   HACS registriert die Karte automatisch als Lovelace-Ressource.
 *
 * Manuelle Installation:
 *   Datei nach /config/www/hikvision-access-card.js kopieren und
 *   als Ressource (/local/hikvision-access-card.js, Typ: JavaScript-Modul) eintragen.
 */

/* ══════════════════════════════════════════════════════════════════════
   KARTE
   ══════════════════════════════════════════════════════════════════════ */
class HikvisionAccessCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    if (!config.device) {
      throw new Error(
        "Pflichtfeld 'device' fehlt — Beispiel: device: hintereingang_halle"
      );
    }
    this._config = config;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _s(entityId) {
    return this._hass?.states?.[entityId] ?? null;
  }

  _val(entityId, fallback = "—") {
    const s = this._s(entityId);
    if (!s || ["unavailable", "unknown", "none"].includes(s.state)) return fallback;
    return s.state;
  }

  _fmtTime(isoString) {
    if (!isoString || ["unavailable", "unknown", "—"].includes(isoString)) return "—";
    try {
      return new Date(isoString).toLocaleString("de-DE", {
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
    } catch {
      return isoString;
    }
  }

  _render() {
    if (!this._config || !this._hass) return;

    const p = this._config.device;
    const title =
      this._config.title ||
      p.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

    const doorState    = this._val(`binary_sensor.${p}_tur`);
    const motionState  = this._val(`binary_sensor.${p}_bewegungsmelder`);
    const personState  = this._val(`sensor.${p}_letzte_person`);
    const eventState   = this._val(`sensor.${p}_letztes_event`);
    const evTimeState  = this._val(`sensor.${p}_zeit_des_letzten_events`);
    const accessState  = this._val(`sensor.${p}_zugang`);
    const devStatus    = this._val(`sensor.${p}_geratestatus`);
    const lockEntityId = `switch.${p}_zugangssperre`;
    const lockState    = this._val(lockEntityId);
    const locked       = lockState === "on";

    const doorOpen     = doorState === "on";
    const motionActive = motionState === "on";
    const connected    = devStatus === "connected";
    const granted      = accessState === "granted";
    const denied       = accessState === "denied";

    const doorColor   = doorOpen  ? "var(--warning-color,#FF9800)"  : "var(--success-color,#4CAF50)";
    const accessColor = granted   ? "var(--success-color,#4CAF50)"  :
                        denied    ? "var(--error-color,#F44336)"     :
                                    "var(--secondary-text-color)";
    const statusColor = connected ? "var(--success-color,#4CAF50)"  : "var(--error-color,#F44336)";

    const doorLabel   = doorOpen  ? "Geöffnet"   : doorState === "—" ? "—" : "Geschlossen";
    const doorIcon    = doorOpen  ? "mdi:door-open"  : "mdi:door-closed";
    const accessLabel = granted   ? "Gewährt"    : denied ? "Verweigert" : "—";
    const accessIcon  = granted   ? "mdi:check-circle" : denied ? "mdi:close-circle" : "mdi:minus-circle-outline";

    // Mushroom-style shape colors (icon bg = color at 15% opacity via hex alpha)
    const doorShapeBg   = doorOpen  ? "#FF980026" : "#4CAF5026";
    const motionShapeBg = motionActive ? "#FF980026" : "rgba(var(--rgb-primary-text-color,0,0,0),.06)";
    const personShapeBg = "rgba(var(--rgb-primary-color,3,169,244),.15)";
    const accessShapeBg = granted ? "#4CAF5026" : denied ? "#F4433626" : "rgba(var(--rgb-primary-text-color,0,0,0),.06)";
    const lockShapeBg   = locked  ? "#F4433618" : "#4CAF5018";
    const lockColor     = locked  ? "var(--error-color,#F44336)" : "var(--success-color,#4CAF50)";

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card {
          padding: 12px 12px 8px;
          --mush-icon-size: var(--mushroom-icon-size, 38px);
        }

        /* ── Header ── */
        .header {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 12px;
        }
        .shape {
          width: var(--mush-icon-size);
          height: var(--mush-icon-size);
          border-radius: var(--mushroom-shape-border-radius, 50%);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .shape ha-icon { --mdc-icon-size: 20px; }

        .header-info {
          flex: 1;
          min-width: 0;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 7px;
        }
        .header-info:hover .primary { opacity: .7; }
        .primary {
          font-size: var(--mushroom-card-primary-font-size, 14px);
          font-weight: var(--mushroom-card-primary-font-weight, 600);
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          transition: opacity .15s;
        }
        .status-dot {
          width: 6px; height: 6px;
          border-radius: 50%;
          background: ${statusColor};
          flex-shrink: 0;
        }
        .secondary {
          font-size: var(--mushroom-card-secondary-font-size, 12px);
          font-weight: var(--mushroom-card-secondary-font-weight, 400);
          color: var(--secondary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .lock-btn {
          width: var(--mush-icon-size);
          height: var(--mush-icon-size);
          border-radius: var(--mushroom-shape-border-radius, 50%);
          border: none;
          background: ${lockShapeBg};
          display: flex; align-items: center; justify-content: center;
          cursor: pointer; flex-shrink: 0;
          transition: background .2s;
        }
        .lock-btn:hover { filter: brightness(.9); }
        .lock-btn ha-icon { --mdc-icon-size: 20px; color: ${lockColor}; }

        /* ── Grid ── */
        .grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          margin-bottom: 8px;
        }
        .tile {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 10px;
          border-radius: var(--ha-card-border-radius, 10px);
          background: var(--secondary-background-color, rgba(0,0,0,.04));
          cursor: pointer;
          transition: filter .15s;
          min-width: 0;
        }
        .tile:hover { filter: brightness(.95); }
        .tile-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; }

        /* ── History chip ── */
        .event-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 10px;
          border-radius: var(--ha-card-border-radius, 10px);
          background: var(--secondary-background-color, rgba(0,0,0,.04));
          cursor: pointer;
          transition: filter .15s;
        }
        .event-row:hover { filter: brightness(.95); }
        .event-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); flex-shrink: 0; }
        .event-info { flex: 1; min-width: 0; }
        .event-more {
          font-size: 11px;
          font-weight: 500;
          color: var(--primary-color);
          white-space: nowrap;
          flex-shrink: 0;
        }

        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
        .pulsing { animation: pulse 1.2s infinite; }
      </style>

      <ha-card>
        <!-- Header -->
        <div class="header">
          <div class="shape" style="background:rgba(var(--rgb-primary-color,3,169,244),.15)">
            <ha-icon icon="mdi:shield-account" style="color:var(--primary-color)"></ha-icon>
          </div>
          <div class="header-info">
            <span class="primary">${title}</span>
            <span class="status-dot" title="${connected ? "Online" : "Offline"}"></span>
          </div>
          <button class="lock-btn" id="lock-toggle" title="${locked ? "Entsperren" : "Sperren"}">
            <ha-icon icon="${locked ? "mdi:lock" : "mdi:lock-open-variant"}"></ha-icon>
          </button>
        </div>

        <!-- 2×2 Grid -->
        <div class="grid">
          <div class="tile" data-entity="binary_sensor.${p}_tur">
            <div class="shape" style="background:${doorShapeBg}">
              <ha-icon icon="${doorIcon}" style="color:${doorColor}"></ha-icon>
            </div>
            <div class="tile-text">
              <span class="secondary">Tür</span>
              <span class="primary" style="color:${doorColor}">${doorLabel}</span>
            </div>
          </div>

          <div class="tile" data-entity="binary_sensor.${p}_bewegungsmelder">
            <div class="shape" style="background:${motionShapeBg}">
              <ha-icon
                icon="${motionActive ? "mdi:motion-sensor" : "mdi:motion-sensor-off"}"
                style="color:${motionActive ? "var(--warning-color,#FF9800)" : "var(--secondary-text-color)"}"
                class="${motionActive ? "pulsing" : ""}">
              </ha-icon>
            </div>
            <div class="tile-text">
              <span class="secondary">Aktivität</span>
              <span class="primary" style="color:${motionActive ? "var(--warning-color,#FF9800)" : "var(--primary-text-color)"}">
                ${motionActive ? "Aktiv" : "Ruhig"}
              </span>
            </div>
          </div>

          <div class="tile" data-entity="sensor.${p}_letzte_person">
            <div class="shape" style="background:${personShapeBg}">
              <ha-icon icon="mdi:account" style="color:var(--primary-color)"></ha-icon>
            </div>
            <div class="tile-text" style="min-width:0">
              <span class="secondary">Letzte Person</span>
              <span class="primary" style="overflow:hidden;text-overflow:ellipsis">${personState}</span>
            </div>
          </div>

          <div class="tile" data-entity="sensor.${p}_zugang">
            <div class="shape" style="background:${accessShapeBg}">
              <ha-icon icon="${accessIcon}" style="color:${accessColor}"></ha-icon>
            </div>
            <div class="tile-text">
              <span class="secondary">Zugang</span>
              <span class="primary" style="color:${accessColor}">${accessLabel}</span>
            </div>
          </div>
        </div>

        <!-- History -->
        <div class="event-row">
          <ha-icon class="event-icon" icon="mdi:history"></ha-icon>
          <div class="event-info">
            <span class="secondary" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${eventState}</span>
            <span class="secondary" style="opacity:.7">${this._fmtTime(evTimeState)}</span>
          </div>
          <span class="event-more">Mehr &rsaquo;</span>
        </div>
      </ha-card>
    `;

    this._bindClicks(p);
  }

  _navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      bubbles: true, composed: true, detail: { entityId },
    }));
  }

  _bindClicks(p) {
    // Header-Body → more-info Gerätestatus
    const headerBody = this.shadowRoot.querySelector(".header-body");
    if (headerBody) {
      headerBody.addEventListener("click", () =>
        this._moreInfo(`sensor.${p}_geratestatus`)
      );
    }

    // Tiles → more-info der jeweiligen Entität
    this.shadowRoot.querySelectorAll(".tile[data-entity]").forEach((tile) => {
      tile.addEventListener("click", () =>
        this._moreInfo(tile.dataset.entity)
      );
    });

    // Zugangssperre-Toggle
    const lockBtn = this.shadowRoot.querySelector("#lock-toggle");
    if (lockBtn) {
      const lockEntityId = `switch.${p}_zugangssperre`;
      lockBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const locked = this._val(lockEntityId) === "on";
        this._hass.callService("switch", locked ? "turn_off" : "turn_on", {
          entity_id: lockEntityId,
        });
      });
    }

    // Verlauf-Zeile → History-Seite
    const eventRow = this.shadowRoot.querySelector(".event-row");
    if (eventRow) {
      const ids = [
        `sensor.${p}_letztes_event`,
        `sensor.${p}_letzte_person`,
        `binary_sensor.${p}_tur`,
        `sensor.${p}_zugang`,
      ].join(",");
      eventRow.addEventListener("click", () =>
        this._navigate(`/history?entity_id=${ids}`)
      );
    }
  }

  getCardSize() { return 3; }

  static getConfigElement() {
    return document.createElement("hikvision-access-card-editor");
  }

  static getStubConfig() {
    return { device: "hintereingang_halle", title: "" };
  }
}

customElements.define("hikvision-access-card", HikvisionAccessCard);

/* ══════════════════════════════════════════════════════════════════════
   EDITOR
   ══════════════════════════════════════════════════════════════════════ */
class HikvisionAccessCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) { this._hass = hass; }

  _fire(config) {
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true })
    );
  }

  _render() {
    if (!this._config) return;
    this.innerHTML = `
      <style>
        .editor { display: flex; flex-direction: column; gap: 14px; padding: 4px 0; }
        .field label {
          display: block;
          font-size: .8rem;
          font-weight: 500;
          color: var(--secondary-text-color);
          margin-bottom: 4px;
        }
        .field input {
          width: 100%;
          box-sizing: border-box;
          padding: 8px 10px;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: .9rem;
        }
        .field input:focus { outline: none; border-color: var(--primary-color); }
        .hint { font-size: .72rem; color: var(--secondary-text-color); margin-top: 3px; }
      </style>
      <div class="editor">
        <div class="field">
          <label>Gerät (Pflichtfeld)</label>
          <input id="device" type="text"
            value="${this._config.device || ""}"
            placeholder="hintereingang_halle">
          <div class="hint">Entity-Prefix: Gerätename in Kleinbuchstaben, Leerzeichen → _</div>
        </div>
        <div class="field">
          <label>Titel (optional)</label>
          <input id="title" type="text"
            value="${this._config.title || ""}"
            placeholder="Hintereingang Halle">
        </div>
      </div>
    `;
    ["device", "title"].forEach((id) => {
      const el = this.querySelector(`#${id}`);
      if (el) {
        el.addEventListener("input", (e) => {
          this._config = { ...this._config, [id]: e.target.value };
          this._fire(this._config);
        });
      }
    });
  }
}

customElements.define("hikvision-access-card-editor", HikvisionAccessCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "hikvision-access-card",
  name: "Hikvision Access Card",
  description: "Übersicht für Hikvision Face Terminals",
  preview: true,
});
