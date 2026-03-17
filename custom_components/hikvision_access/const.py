"""Constants for the Hikvision Access Control integration."""

DOMAIN = "hikvision_access"
EVENT_TYPE = "hikvision_access_event"

PLATFORMS = ["sensor", "binary_sensor", "switch"]

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_VERIFY_SSL = "verify_ssl"
CONF_NAME = "name"
CONF_WEBHOOK_ID = "webhook_id"
CONF_NOTIFICATION_IP = "notification_ip"
CONF_NOTIFICATION_PORT = "notification_port"

# API endpoints
HTTP_HOSTS_PATH = "/ISAPI/Event/notification/httpHosts"
DEVICE_INFO_PATH = "/ISAPI/System/deviceInfo"
ACS_CAPS_PATH = "/ISAPI/AccessControl/GetAcsEvent/capabilities"
REMOTE_CONTROL_PATH = "/ISAPI/AccessControl/RemoteControl/door/1"

# Remote control commands
CMD_NORMAL = "normal"           # Normalbetrieb (Gesichtserkennung aktiv)
CMD_ALWAYS_CLOSED = "alwaysClosed"  # Dauerhaft gesperrt

# Binary sensor auto-reset duration
BINARY_SENSOR_ACTIVE_SECONDS = 3

# Poll / connection status labels (used by diagnostic sensor)
STREAM_STATUS_CONNECTED = "connected"
STREAM_STATUS_DISCONNECTED = "disconnected"

# Access outcome
ACCESS_STATUS_GRANTED = "granted"
ACCESS_STATUS_DENIED = "denied"

# Human-readable labels for alertStream major_minor event codes.
# The device sends these codes in pushed HTTP notifications.
EVENT_LABELS: dict[str, str] = {
    "5_75": "Zugang gewährt",
    "5_21": "Tür geöffnet",
    "5_22": "Tür geschlossen",
    "3_112": "Fernöffnung",
    "3_80": "Tür geöffnet (Relais)",
    "2_39": "Ereignis erkannt",
    "2_1031": "Zugang verweigert",
    "5_1": "Tür gesperrt",
    "5_2": "Tür normal",
    "5_3": "Normaler Ausgang",
    "5_4": "Ausgang dauerhaft offen",
    "5_5": "Ausgang dauerhaft geschlossen",
}

# Door state codes (from alertStream subEventType values)
DOOR_OPEN_CODES: frozenset[str] = frozenset({"5_21", "3_80"})
DOOR_CLOSE_CODES: frozenset[str] = frozenset({"5_22"})

# Access outcome codes
ACCESS_GRANTED_CODES: frozenset[str] = frozenset({"5_75", "3_112"})
ACCESS_DENIED_CODES: frozenset[str] = frozenset({"2_1031"})
