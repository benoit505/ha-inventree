"""Data coordinator for Inventree integration."""
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import InventreeAPIClient

_LOGGER = logging.getLogger(__name__)

class InventreeDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Inventree data."""

    def __init__(self, hass: HomeAssistant, api_client: InventreeAPIClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Inventree",
            update_interval=timedelta(seconds=30),
        )
        self.api_client = api_client
        self.categories = {}
        self.locations = {}

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            _LOGGER.debug("Starting data update")
            data = {}
            
            # Get category tree
            try:
                data["categories"] = await self.api_client.get_category_tree()
                _LOGGER.debug("Raw categories data: %s", data["categories"])
            except Exception as e:
                _LOGGER.error("Error fetching categories: %s", e)
                data["categories"] = []

            # Get stock locations
            try:
                data["locations"] = await self.api_client.get_stock_locations()
            except Exception as e:
                _LOGGER.error("Error fetching locations: %s", e)
                data["locations"] = []

            # Get all items
            try:
                data["items"] = await self.api_client.get_items()
                _LOGGER.debug("Raw items data: %s", data["items"])
            except Exception as e:
                _LOGGER.error("Error fetching items: %s", e)
                data["items"] = []

            # Get low stock items
            try:
                data["low_stock"] = await self.api_client.get_low_stock_items()
            except Exception as e:
                _LOGGER.error("Error fetching low stock items: %s", e)
                data["low_stock"] = []

            # Get parameters for parts that have them
            try:
                parameters = {}
                if data["items"]:
                    for item in data["items"]:
                        part_id = item.get('pk')
                        if part_id:
                            params = await self.api_client.get_part_parameters(part_id)
                            if params:  # Only store if parameters exist
                                parameters[part_id] = params
                data["parameters"] = parameters
                _LOGGER.debug("Raw parameters data: %s", parameters)
            except Exception as e:
                _LOGGER.error("Error fetching parameters: %s", e)
                data["parameters"] = {}

            return data

        except Exception as err:
            _LOGGER.error("Error fetching Inventree data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_shutdown(self) -> None:
        """Close API client session when coordinator is shutdown."""
        if self.api_client:
            await self.api_client.close()