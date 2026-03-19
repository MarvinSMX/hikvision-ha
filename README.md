# Hikvision Access Control für Home Assistant

HACS-Integration für Hikvision Face Terminal und Access Controller (z. B. DS-K1T671).  
Verbindet sich dauerhaft per HTTPS mit dem Gerät und liefert Zutritts-Events, Personenerkennung und Türstatus in Echtzeit nach Home Assistant.

---

## Voraussetzungen

- Home Assistant 2023.1 oder neuer
- HACS installiert
- Hikvision Access Controller im lokalen Netzwerk erreichbar
- Admin-Benutzername und Passwort des Geräts

---

## Installation

1. HACS öffnen → **Integrationen** → Menü oben rechts → **Benutzerdefinierte Repositories**
2. URL dieses Repositories eintragen, Typ **Integration** auswählen → **Hinzufügen**
3. Integration **Hikvision Access Control** suchen und **Herunterladen**
4. Home Assistant neu starten
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Hikvision Access Control**

### Lovelace-Karten (optional, eigene HACS-Repos)

| Repo | Karte |
|------|--------|
| [hikvision-access-card](https://github.com/yourusername/hikvision-access-card) | Ein Terminal: `custom:hikvision-access-card` |
| [hikvision-access-overview-card](https://github.com/yourusername/hikvision-access-overview-card) | Mehrere Terminals: `custom:hikvision-access-overview-card` |

Jeweils unter HACS → **Frontend** als **Lovelace**-Repository hinzufügen und installieren.

---

## Einrichtung

Beim Hinzufügen der Integration erscheinen zwei Schritte:

**Schritt 1 – Verbindungsdaten**

| Feld | Beschreibung |
|------|-------------|
| Host | IP-Adresse oder Hostname des Geräts (z. B. `192.168.178.20`) |
| Benutzername | Admin-Benutzername des Geräts |
| Passwort | Passwort (wird verschlüsselt gespeichert) |
| SSL verifizieren | Bei selbstsigniertem Zertifikat **deaktiviert** lassen |

**Schritt 2 – Gerätename bestätigen**

Die Integration liest beim Verbinden automatisch den Gerätenamen aus dem ersten Event (`deviceName`) aus und schlägt ihn als Anzeigenamen vor. Du kannst ihn hier anpassen.

---

## Entities

Nach der Einrichtung erscheinen folgende Entities unter dem Gerät:

### Sensoren

| Entity | Beschreibung | Beispielwert |
|--------|-------------|--------------|
| `sensor.{name}_last_event` | Letztes Ereignis in Klartext | `Zugang gewährt` |
| `sensor.{name}_last_event_time` | Zeitstempel des letzten Ereignisses | `2024-07-26T15:56:48+02:00` |
| `sensor.{name}_last_person` | Name der zuletzt erkannten Person | `Max Mustermann` |
| `sensor.{name}_zugang` | Letzter Zugangsstatus | `granted` / `denied` |
| `sensor.{name}_stream_status` | Verbindungsstatus zur Kamera | `connected` |

**`sensor.{name}_zugang`** — Zustände:

| Zustand | Bedeutung |
|---------|-----------|
| `granted` | Zugang gewährt (Gesicht / Karte / Fingerabdruck erkannt) |
| `denied` | Zugang verweigert |
| *(leer)* | Noch kein Zugangs-Event seit HA-Start |

Der Sensor bleibt dauerhaft im letzten Zustand. Für wiederholte Automation-Trigger nutze den [Event Bus](#event-bus).

**`sensor.{name}_last_person`** — Attribute:

| Attribut | Beschreibung |
|----------|-------------|
| `timestamp` | Zeitpunkt der Erkennung |
| `card_no` | Kartennummer |
| `employee_no` | Mitarbeiternummer |
| `verify_mode` | Verifizierungsmethode (`cardOrFaceOrFp`) |
| `verify_no` | Laufende Verifizierungsnummer |

---

### Binary Sensoren

| Entity | Beschreibung |
|--------|-------------|
| `binary_sensor.{name}_tür` | `on` = Tür offen, `off` = Tür geschlossen |
| `binary_sensor.{name}_event_active` | 3 Sekunden `on` bei jedem eingehenden Event |

---

## Event Bus

Bei **jedem** eingehenden Event wird `hikvision_access_event` auf dem HA Event Bus gefeuert.  
Damit lassen sich auch mehrfach aufeinanderfolgende Events vom selben Typ zuverlässig in Automationen auslösen.

**Payload:**

```yaml
device_name: "Living Room"
ip: "10.69.100.207"
timestamp: "2024-07-26T15:56:48+02:00"
event_code: "5_75"
event_label: "Zugang gewährt"
major: 5
sub: 75
person_name: "Max Mustermann"
employee_no: "245"
verify_mode: "cardOrFaceOrFp"
verify_no: 238
serial_no: 277
```

---

## Automationen

### Benachrichtigung bei Zugang

```yaml
automation:
  - alias: "Zutritt erkannt"
    trigger:
      - platform: state
        entity_id: sensor.living_room_zugang
        to: "granted"
    action:
      - service: notify.mobile_app_dein_handy
        data:
          title: "Zutritt"
          message: >
            {{ state_attr('sensor.living_room_last_person', 'timestamp') | as_timestamp | timestamp_custom('%H:%M') }}
            Uhr – {{ states('sensor.living_room_last_person') }}
```

### Zugang verweigert – Alarm

```yaml
automation:
  - alias: "Zugang verweigert – Alarm"
    trigger:
      - platform: state
        entity_id: sensor.living_room_zugang
        to: "denied"
    action:
      - service: notify.mobile_app_dein_handy
        data:
          title: "Zugang verweigert!"
          message: "Unbekannte Person am Living Room"
```

### Tür bleibt offen – Warnung

```yaml
automation:
  - alias: "Tür offen – Warnung nach 30 Sekunden"
    trigger:
      - platform: state
        entity_id: binary_sensor.living_room_tür
        to: "on"
        for: "00:00:30"
    action:
      - service: notify.mobile_app_dein_handy
        data:
          message: "Achtung: Living Room seit 30 Sekunden offen!"
```

### Event Bus – wiederholte Events auslösen

```yaml
automation:
  - alias: "Jeden Zutritt loggen"
    trigger:
      - platform: event
        event_type: hikvision_access_event
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.event_label == 'Zugang gewährt' }}"
    action:
      - service: logbook.log
        data:
          name: "Living Room"
          message: >
            {{ trigger.event.data.person_name }} –
            {{ trigger.event.data.timestamp }}
```

---

## Bekannte Event-Codes

Die Integration übersetzt bekannte Codes automatisch in Klartext.  
Unbekannte Codes erscheinen als `major_sub` (z. B. `2_39`) und können in `const.py` ergänzt werden.

| Code | Klartext | Beschreibung |
|------|----------|-------------|
| `5_75` | Zugang gewährt | Gesicht / Karte / Fingerabdruck erfolgreich |
| `5_22` | Tür geöffnet | Türkontakt: offen |
| `5_21` | Tür geschlossen | Türkontakt: geschlossen |
| `3_112` | Fernöffnung | Öffnung per Software / Innenknopf |
| `3_80` | Tür geöffnet (Relais) | Relais hat ausgelöst |
| `2_39` | Ereignis erkannt | Bedeutung gerätespezifisch |
| `2_1031` | Zugang verweigert | Unbekannte Person / Verifikation fehlgeschlagen |

> Eigene Codes kannst du durch Testen am Gerät ermitteln und in `custom_components/hikvision_access/const.py` unter `EVENT_LABELS` eintragen.

---

## Verbindungs-Diagnose

`sensor.{name}_stream_status` zeigt den aktuellen Zustand der Stream-Verbindung:

| Zustand | Bedeutung |
|---------|-----------|
| `connected` | Verbunden, Events werden empfangen |
| `reconnecting` | Verbindungsaufbau läuft |
| `disconnected` | Verbindung getrennt, nächster Versuch in 5 s |

Die Integration verbindet sich bei Verbindungsverlust automatisch neu.

---

## Fehlerbehebung

**Integration wird nicht gefunden in HACS**  
→ Repository unter *Benutzerdefinierte Repositories* hinzufügen (siehe Installation)

**Verbindung schlägt fehl**  
→ IP-Adresse und Netzwerkzugang vom HA-Host zum Gerät prüfen  
→ SSL verifizieren deaktivieren (Gerät nutzt selbstsigniertes Zertifikat)

**Authentifizierung fehlgeschlagen**  
→ Benutzername und Passwort prüfen. Der Benutzer benötigt ISAPI-Zugriff (Admin-Rechte)

**Kein Stream, keine Events**  
→ Am Gerät prüfen: Einstellungen → Netzwerk → Erweiterte Einstellungen → HTTPS aktiviert?  
→ HA-Logs unter *Einstellungen → System → Logs* auf Fehler von `hikvision_access` prüfen
