import logging
from typing import Any, Dict, Optional
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_API_URL, CONF_API_KEY, CONF_WEBSOCKET_URL, CONF_ENABLE_WEBSOCKET
from .api import InventreeAPIClient

_LOGGER = logging.getLogger(__name__)

class InventreeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Inventree."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                await self._test_credentials(user_input[CONF_API_URL], user_input[CONF_API_KEY])
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title="Inventree", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_URL): str,
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_WEBSOCKET_URL, default=""): str,
                vol.Optional(CONF_ENABLE_WEBSOCKET, default=True): bool,
            }),
            errors=errors,
        )

    async def _test_credentials(self, api_url: str, api_key: str) -> None:
        """Validate credentials."""
        client = InventreeAPIClient(api_url, api_key)
        try:
            await client.async_init()
            if not await client.test_connection():
                raise CannotConnect
        except Exception as exception:
            raise CannotConnect from exception
        finally:
            await client.close()

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""