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
