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
            
            # Get all items with rich data
            try:
                data["items"] = await self.api_client.get_items()
                _LOGGER.debug("Fetched %d items with rich data", len(data["items"]))
                
                # Verify we have pk for each item
                for item in data["items"]:
                    if not item.get('pk'):
                        _LOGGER.warning("Item missing pk: %s", item.get('name', 'Unknown'))
                    if not item.get('thumbnail'):
                        _LOGGER.debug("Item missing thumbnail: %s", item.get('name', 'Unknown'))
            except Exception as e:
                _LOGGER.error("Error fetching items: %s", e)
                data["items"] = []

            # Get category tree for organization
            try:
                data["categories"] = await self.api_client.get_category_tree()
                _LOGGER.debug("Fetched category tree")
            except Exception as e:
                _LOGGER.error("Error fetching categories: %s", e)
                data["categories"] = []

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
            except Exception as e:
                _LOGGER.error("Error fetching parameters: %s", e)
                data["parameters"] = {}

            # Store metadata including images
            try:
                metadata = {}
                if data["items"]:
                    for item in data["items"]:
                        part_id = item.get('pk')
                        if part_id:
                            details = await self.api_client.get_part_details(part_id)
                            if details:
                                _LOGGER.debug(
                                    "Got metadata for part %s: image=%s, thumbnail=%s",
                                    part_id,
                                    details.get('image'),
                                    details.get('thumbnail')
                                )
                                metadata[part_id] = {
                                    'image': details.get('image'),
                                    'thumbnail': details.get('thumbnail')
                                }
                data["metadata"] = metadata
                _LOGGER.debug("Final metadata: %s", metadata)
            except Exception as e:
                _LOGGER.error("Error fetching metadata: %s", e)
                data["metadata"] = {}

            return data

        except Exception as err:
            _LOGGER.error("Error fetching Inventree data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_shutdown(self) -> None:
        """Close API client session when coordinator is shutdown."""
        if self.api_client:
            await self.api_client.close()