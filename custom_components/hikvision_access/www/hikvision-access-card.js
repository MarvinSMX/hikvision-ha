/**
 * Hikvision Access Card
 * Lovelace custom card für Hikvision Face Terminals.
 *
 * Wird automatisch beim Start der Integration als Frontend-Ressource
 * registriert — keine manuelle Konfiguration erforderlich.
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

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 0; overflow: hidden; }

        /* ── Header ─────────────────────────────── */
        .header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 14px 16px 10px;
          border-bottom: 1px solid var(--divider-color);
        }
        .header ha-icon {
          --mdc-icon-size: 24px;
          color: var(--primary-color);
        }
        .header-title {
          flex: 1;
          font-size: 1rem;
          font-weight: 600;
          color: var(--primary-text-color);
        }
        .status-pill {
          display: flex;
          align-items: center;
          gap: 5px;
          font-size: 0.72rem;
          font-weight: 500;
          color: ${statusColor};
          background: ${statusColor}22;
          padding: 2px 8px;
          border-radius: 99px;
        }
        .status-dot {
          width: 7px; height: 7px;
          border-radius: 50%;
          background: ${statusColor};
        }

        /* ── Grid ────────────────────────────────── */
        .grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1px;
          background: var(--divider-color);
          border-bottom: 1px solid var(--divider-color);
        }
        .tile {
          background: var(--card-background-color);
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 3px;
        }
        .tile-label {
          font-size: 0.7rem;
          text-transform: uppercase;
          letter-spacing: .05em;
          color: var(--secondary-text-color);
        }
        .tile-value {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: .95rem;
          font-weight: 600;
        }
        .tile-value ha-icon { --mdc-icon-size: 17px; }

        /* ── Event row ───────────────────────────── */
        .event-row {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
        }
        .event-icon { --mdc-icon-size: 20px; color: var(--primary-color); flex-shrink: 0; }
        .event-info { flex: 1; min-width: 0; }
        .event-label {
          font-size: .88rem;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .event-time { font-size: .73rem; color: var(--secondary-text-color); margin-top: 1px; }

        /* ── Motion pulse ────────────────────────── */
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
        .pulsing { animation: pulse 1.2s infinite; }
      </style>

      <ha-card>
        <div class="header">
          <ha-icon icon="mdi:shield-account"></ha-icon>
          <span class="header-title">${title}</span>
          <div class="status-pill">
            <div class="status-dot"></div>
            ${connected ? "Online" : "Offline"}
          </div>
        </div>

        <div class="grid">
          <!-- Tür -->
          <div class="tile">
            <div class="tile-label">Tür</div>
            <div class="tile-value" style="color:${doorColor}">
              <ha-icon icon="${doorIcon}"></ha-icon>
              ${doorLabel}
            </div>
          </div>

          <!-- Aktivität -->
          <div class="tile">
            <div class="tile-label">Aktivität</div>
            <div class="tile-value" style="color:${motionActive ? "var(--warning-color,#FF9800)" : "var(--secondary-text-color)"}">
              <ha-icon
                icon="${motionActive ? "mdi:motion-sensor" : "mdi:motion-sensor-off"}"
                class="${motionActive ? "pulsing" : ""}">
              </ha-icon>
              ${motionActive ? "Aktiv" : "Ruhig"}
            </div>
          </div>

          <!-- Person -->
          <div class="tile">
            <div class="tile-label">Letzte Person</div>
            <div class="tile-value">
              <ha-icon icon="mdi:account" style="color:var(--primary-color)"></ha-icon>
              <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${personState}</span>
            </div>
          </div>

          <!-- Zugang -->
          <div class="tile">
            <div class="tile-label">Zugang</div>
            <div class="tile-value" style="color:${accessColor}">
              <ha-icon icon="${accessIcon}"></ha-icon>
              ${accessLabel}
            </div>
          </div>
        </div>

        <!-- Letztes Event -->
        <div class="event-row">
          <ha-icon class="event-icon" icon="mdi:history"></ha-icon>
          <div class="event-info">
            <div class="event-label">${eventState}</div>
            <div class="event-time">${this._fmtTime(evTimeState)}</div>
          </div>
        </div>
      </ha-card>
    `;
  }

  getCardSize() {
    return 3;
  }

  static getConfigElement() {
    return document.createElement("hikvision-access-card-editor");
  }

  static getStubConfig() {
    return { device: "hintereingang_halle", title: "" };
  }
}

customElements.define("hikvision-access-card", HikvisionAccessCard);

/* ══════════════════════════════════════════════════════════════════════
   EDITOR  (erscheint im Lovelace-Konfigurationsdialog)
   ══════════════════════════════════════════════════════════════════════ */
class HikvisionAccessCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _fire(config) {
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true })
    );
  }

  _render() {
    if (!this._config) return;
    this.innerHTML = `
      <style>
        .editor { display: flex; flex-direction: column; gap: 12px; padding: 8px 0; }
        label { font-size: .85rem; color: var(--secondary-text-color); display: block; margin-bottom: 3px; }
        ha-textfield { width: 100%; }
      </style>
      <div class="editor">
        <div>
          <label>Gerät (Entity-Prefix, Pflichtfeld)</label>
          <ha-textfield
            id="device"
            .value="${this._config.device || ""}"
            placeholder="hintereingang_halle"
            helper="Gerätename in Kleinbuchstaben, Leerzeichen → _">
          </ha-textfield>
        </div>
        <div>
          <label>Titel (optional)</label>
          <ha-textfield
            id="title"
            .value="${this._config.title || ""}"
            placeholder="Hintereingang Halle">
          </ha-textfield>
        </div>
      </div>
    `;

    ["device", "title"].forEach((id) => {
      const el = this.querySelector(`#${id}`);
      if (el) {
        el.addEventListener("change", (e) => {
          this._config = { ...this._config, [id]: e.target.value.trim() };
          this._fire(this._config);
        });
      }
    });
  }
}

customElements.define("hikvision-access-card-editor", HikvisionAccessCardEditor);

/* ── HACS / Lovelace card registry ──────────────────────────────────── */
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hikvision-access-card",
  name: "Hikvision Access Card",
  description: "Übersicht für Hikvision Face Terminals",
  preview: true,
  documentationURL:
    "https://github.com/mlaenger/hikvision-ha#lovelace-karte",
});
