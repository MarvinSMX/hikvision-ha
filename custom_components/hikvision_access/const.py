"""Constants for the Hikvision Access Control integration."""

DOMAIN = "hikvision_access"
EVENT_TYPE = "hikvision_access_event"

PLATFORMS = ["sensor", "binary_sensor"]

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_VERIFY_SSL = "verify_ssl"
CONF_NAME = "name"

# API endpoints
ACS_EVENT_PATH = "/ISAPI/AccessControl/AcsEvent"
DEVICE_INFO_PATH = "/ISAPI/System/deviceInfo"
ACS_CAPS_PATH = "/ISAPI/AccessControl/GetAcsEvent/capabilities"

# Polling
POLL_INTERVAL = 3  # seconds between AcsEvent polls

# HA storage
STORAGE_VERSION = 1

# Binary sensor pulse duration
BINARY_SENSOR_ACTIVE_SECONDS = 3

# Stream / poll status labels (used by diagnostic sensor)
STREAM_STATUS_CONNECTED = "connected"
STREAM_STATUS_DISCONNECTED = "disconnected"

# Access outcome labels
ACCESS_STATUS_GRANTED = "granted"
ACCESS_STATUS_DENIED = "denied"

# inductiveEventType values (Hikvision semantic classification)
# Much more reliable than raw major/minor code mapping.
INDUCTIVE_EVENT_LABELS: dict[int, str] = {
    1: "Zugang gewährt",
    2: "Zugang verweigert",
    3: "Tür geöffnet",
    4: "Tür geschlossen",
    5: "Tür Ausnahme",
    6: "Fernöffnung",
    8: "Gerät Ausnahme",
    9: "Gerät wiederhergestellt",
    10: "Alarm",
    11: "Alarm beendet",
    12: "Intercom",
}

INDUCTIVE_GRANTED: frozenset[int] = frozenset({1})
INDUCTIVE_DENIED: frozenset[int] = frozenset({2})
INDUCTIVE_DOOR_OPEN: frozenset[int] = frozenset({3})
INDUCTIVE_DOOR_CLOSE: frozenset[int] = frozenset({4})

# Fallback labels for devices that don't supply inductiveEventType.
# Keys are "major_minor" in decimal (as returned by the JSON API).
EVENT_LABELS: dict[str, str] = {
    "5_75": "Zugang gewährt",
    "5_22": "Tür geöffnet",
    "5_21": "Tür geschlossen",
    "3_112": "Fernöffnung",
    "3_80": "Tür geöffnet (Relais)",
    "2_39": "Ereignis erkannt",
    "2_1031": "Zugang verweigert",
}

# Event codes that map to access outcomes (fallback if no inductiveEventType)
ACCESS_GRANTED_CODES: frozenset[str] = frozenset({"5_75"})
ACCESS_DENIED_CODES: frozenset[str] = frozenset({"2_1031"})
