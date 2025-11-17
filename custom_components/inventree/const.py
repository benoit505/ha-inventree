"""Constants for Inventree integration."""
DOMAIN = "inventree"
CONF_API_URL = "api_url"
CONF_API_KEY = "api_key"
CONF_WEBSOCKET_URL = "websocket_url"
CONF_ENABLE_WEBSOCKET = "enable_websocket"

DEFAULT_SCAN_INTERVAL = 300  # 5 minutes

# WebSocket settings
DEFAULT_WEBSOCKET_PORT = 9020

# For development
DEBUG = True