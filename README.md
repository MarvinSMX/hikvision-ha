# Hikvision Access Control – Home Assistant Integration

HACS-kompatible Custom Integration für Hikvision Face Terminal / Access Controller (DS-K1T671 u.ä.).

## Funktionsweise

Die Integration verbindet sich dauerhaft per HTTPS Digest Auth mit dem ISAPI alertStream-Endpoint des Gerätes und verarbeitet jeden eingehenden `AccessControllerEvent` in Echtzeit.

## Voraussetzungen

- Home Assistant 2023.1 oder neuer
- Hikvision Access Controller mit aktiviertem ISAPI-Eventstream
- Netzwerkzugang vom HA-Host zum Gerät

## Installation via HACS

1. HACS öffnen → **Integrationen** → **Benutzerdefinierte Repositories**
2. URL dieses Repositories eintragen, Typ: **Integration**
3. **Hikvision Access Control** suchen und installieren
4. Home Assistant neu starten
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Hikvision Access Control**

## Konfigurationsfelder

| Feld | Beschreibung |
|------|-------------|
| Host | IP-Adresse oder Hostname des Gerätes |
| Benutzername | Admin-Benutzer des Gerätes |
| Passwort | Passwort des Benutzers |
| SSL verifizieren | Bei selbstsigniertem Zertifikat: deaktiviert lassen |
| Name | Anzeigename der Integration (z. B. "Hintereingang") |

## Bereitgestellte Entities

### Sensoren

- `sensor.{name}_last_event` – Letzter Event-Code (`major_sub`, z. B. `2_39`)
- `sensor.{name}_last_event_time` – Zeitstempel des letzten Events
- `sensor.{name}_stream_status` – Verbindungsstatus (`connected` / `disconnected` / `reconnecting`)

### Binary Sensoren

- `binary_sensor.{name}_last_event_active` – Für 3 Sekunden `on` bei jedem eingehenden Event

## HA Event Bus

Bei jedem Event wird `hikvision_access_event` gefeuert:

```yaml
event_type: hikvision_access_event
event_data:
  device_name: "Hintereingang Halle"
  ip: "10.69.100.207"
  timestamp: "2023-11-06T22:39:31+01:00"
  event_code: "3_80"
  major: 3
  sub: 80
  verify_no: 168
  serial_no: 24
```

## Beispiel-Automation

```yaml
automation:
  - alias: "Hikvision Zutritt erkannt"
    trigger:
      platform: event
      event_type: hikvision_access_event
    condition:
      condition: template
      value_template: "{{ trigger.event.data.event_code == '2_39' }}"
    action:
      service: notify.mobile_app_dein_handy
      data:
        message: "Zugang: {{ trigger.event.data.device_name }}"
```

## Bekannte Event-Codes (Hikvision DS-K1T671)

| Code | Bedeutung (zu verifizieren) |
|------|---------------------------|
| `2_39` | Erfolgreich verifiziert (Gesicht / Karte) |
| `2_1031` | Unbekannte Person / Verifikation fehlgeschlagen |
| `3_80` | Tür geöffnet (Relais) |
| `3_112` | Remote-Öffnung (Innenknopf / Software) |

> Die Bedeutungen sollten durch eigene Tests am Gerät verifiziert werden.
