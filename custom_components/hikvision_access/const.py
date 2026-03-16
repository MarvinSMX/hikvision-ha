"""Constants for the Hikvision Access Control integration."""

DOMAIN = "hikvision_access"
EVENT_TYPE = "hikvision_access_event"

PLATFORMS = ["sensor", "binary_sensor"]

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_VERIFY_SSL = "verify_ssl"
CONF_NAME = "name"

STREAM_PATH = "/ISAPI/Event/notification/alertStream"

RECONNECT_DELAY = 5
BINARY_SENSOR_ACTIVE_SECONDS = 3

STREAM_STATUS_CONNECTED = "connected"
STREAM_STATUS_DISCONNECTED = "disconnected"
STREAM_STATUS_RECONNECTING = "reconnecting"

# AccessControllerEvent sub-types observed on DS-K1T671
ACE_SUB_PERSON_VERIFIED = 75
ACE_SUB_DOOR_CLOSED = 21
ACE_SUB_DOOR_OPEN = 22
ACE_MAJOR_ACCESS = 5

# Human-readable labels for known event codes (major_sub).
# Extend this dict as you discover new codes on your device.
EVENT_LABELS: dict[str, str] = {
    "5_75": "Zugang gewährt",
    "5_22": "Tür geöffnet",
    "5_21": "Tür geschlossen",
    "3_112": "Fernöffnung",
    "3_80": "Tür geöffnet (Relais)",
    "2_39": "Ereignis erkannt",
    "2_1031": "Zugang verweigert",
}

# Event codes that map to an access outcome (sensor.access_status)
ACCESS_GRANTED_CODES: frozenset[str] = frozenset({"5_75"})
ACCESS_DENIED_CODES: frozenset[str] = frozenset({"2_1031"})

ACCESS_STATUS_GRANTED = "granted"
ACCESS_STATUS_DENIED = "denied"
