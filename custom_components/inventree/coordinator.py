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
                
                # Process thumbnails for each item
                for item in data["items"]:
                    if not item.get('pk'):
                        _LOGGER.warning("Item missing pk: %s", item.get('name', 'Unknown'))
                        continue
                        
                    try:
                        # Get detailed info including downloaded thumbnail
                        details = await self.api_client.get_part_details(item['pk'])
                        if details.get('thumbnail'):
                            item['thumbnail'] = details['thumbnail']
                            _LOGGER.debug("Updated thumbnail for item %s: %s", 
                                        item.get('name'), item['thumbnail'])
                    except Exception as thumb_err:
                        _LOGGER.error("Error processing thumbnail for item %s: %s", 
                                    item.get('name'), thumb_err)
                        
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

            # Parameters are now included in items response
            data["parameters"] = {}
            data["metadata"] = {}

            _LOGGER.debug("Data update complete with %d items", len(data["items"]))
            return data

        except Exception as err:
            _LOGGER.error("Error fetching Inventree data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_shutdown(self) -> None:
        """Close API client session when coordinator is shutdown."""
        if self.api_client:
            await self.api_client.close()