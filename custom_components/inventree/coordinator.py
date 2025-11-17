"""Data coordinator for Inventree integration."""
import logging
import os
import json
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.util import dt as dt_util

from .api import InventreeAPIClient

_LOGGER = logging.getLogger(__name__)

# Thumbnail cache settings
THUMBNAIL_CACHE_FILE = "inventree_thumbnail_cache.json"
THUMBNAIL_REFRESH_INTERVAL = timedelta(hours=24)  # Refresh thumbnails once per day

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
        self.hass = hass
        self.thumbnail_cache = self._load_thumbnail_cache()

    def _get_cache_file_path(self):
        """Get the path to the thumbnail cache file."""
        return os.path.join(self.hass.config.path(), THUMBNAIL_CACHE_FILE)

    def _load_thumbnail_cache(self):
        """Load the thumbnail cache from disk."""
        try:
            cache_file = self._get_cache_file_path()
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    cache = json.load(f)
                    _LOGGER.debug("Loaded thumbnail cache with %d entries", len(cache))
                    return cache
        except Exception as e:
            _LOGGER.warning("Failed to load thumbnail cache: %s", e)
        
        return {}  # Return empty cache if file doesn't exist or there's an error

    def _save_thumbnail_cache(self):
        """Save the thumbnail cache to disk."""
        try:
            cache_file = self._get_cache_file_path()
            with open(cache_file, 'w') as f:
                json.dump(self.thumbnail_cache, f)
            _LOGGER.debug("Saved thumbnail cache with %d entries", len(self.thumbnail_cache))
        except Exception as e:
            _LOGGER.warning("Failed to save thumbnail cache: %s", e)

    def _should_update_thumbnail(self, part_id):
        """Determine if a thumbnail should be updated based on cache."""
        # If part not in cache, always update
        if str(part_id) not in self.thumbnail_cache:
            return True
            
        # Check if the cached thumbnail is older than the refresh interval
        last_updated = self.thumbnail_cache.get(str(part_id), {}).get('last_updated')
        if not last_updated:
            return True
            
        try:
            last_updated_dt = dt_util.parse_datetime(last_updated)
            if not last_updated_dt:
                return True
                
            now = dt_util.now()
            return (now - last_updated_dt) > THUMBNAIL_REFRESH_INTERVAL
        except Exception:
            # If there's any error parsing the date, update the thumbnail
            return True

    def _update_thumbnail_cache(self, part_id, thumbnail_path):
        """Update the thumbnail cache for a part."""
        self.thumbnail_cache[str(part_id)] = {
            'path': thumbnail_path,
            'last_updated': dt_util.now().isoformat()
        }

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            start_time = dt_util.now()
            _LOGGER.debug("Starting data update")
            data = {}
            
            # Get all items with rich data
            try:
                data["items"] = await self.api_client.get_items()
                _LOGGER.debug("Fetched %d items with rich data", len(data["items"]))
                
                # Process thumbnails and parameters for each item
                data["parameters"] = {}  # Initialize parameters dictionary
                
                for item in data["items"]:
                    if not item.get('pk'):
                        _LOGGER.warning("Item missing pk: %s", item.get('name', 'Unknown'))
                        continue
                        
                    try:
                        # Check if we need to update the thumbnail
                        download_thumbnail = self._should_update_thumbnail(item['pk'])
                        
                        if download_thumbnail:
                            _LOGGER.debug("Updating thumbnail for part %s", item['pk'])
                            # Get detailed info including downloaded thumbnail
                            details = await self.api_client.get_part_details(item['pk'], download_thumbnails=True)
                            if details.get('thumbnail'):
                                item['thumbnail'] = details['thumbnail']
                                _LOGGER.debug("Updated thumbnail for item %s: %s", 
                                            item.get('name'), item['thumbnail'])
                                # Update the cache
                                self._update_thumbnail_cache(item['pk'], details['thumbnail'])
                        else:
                            # Use cached thumbnail path
                            cached_path = self.thumbnail_cache.get(str(item['pk']), {}).get('path')
                            if cached_path:
                                item['thumbnail'] = cached_path
                                _LOGGER.debug("Using cached thumbnail for item %s: %s", 
                                            item.get('name'), cached_path)
                            
                            # Still get part details but skip thumbnail download
                            details = await self.api_client.get_part_details(item['pk'], download_thumbnails=False)
                        
                        # Get parameters for this item
                        params = await self.api_client.get_part_parameters(item['pk'])
                        if params:
                            data["parameters"][str(item['pk'])] = params
                            _LOGGER.debug("Fetched %d parameters for item %s", 
                                        len(params), item.get('name'))
                            
                        # Add barcode info
                        item['barcode_hash'] = details.get('barcode_hash', '')
                        _LOGGER.debug("Added barcode hash for item %s: %s", 
                                    item.get('name'), item.get('barcode_hash', ''))
                            
                        # Get category hierarchy
                        try:
                            category = await self.get_category(item['category'])
                            item["category_pathstring"] = category["pathstring"]
                            item["dashboard_url"] = f"/dashboard-{category['pathstring'].lower().replace('/', '/')}"
                            item["inventree_url"] = f"/part/{item['pk']}/"
                        except Exception as hier_err:
                            _LOGGER.error(f"Error getting hierarchy for item {item.get('name')}: {hier_err}")
                            
                    except Exception as detail_err:
                        _LOGGER.error("Error processing details for item %s: %s", 
                                    item.get('name'), detail_err)
                        # Ensure barcode_hash exists even on error
                        item['barcode_hash'] = ''
                        
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

            data["metadata"] = {}
            
            # Save the thumbnail cache
            self._save_thumbnail_cache()

            end_time = dt_util.now()
            duration = (end_time - start_time).total_seconds()
            _LOGGER.debug("Data update complete with %d items and %d items with parameters in %.3f seconds", 
                         len(data["items"]), len(data["parameters"]), duration)
            return data

        except Exception as err:
            _LOGGER.error("Error fetching Inventree data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_shutdown(self) -> None:
        """Close API client session when coordinator is shutdown."""
        if self.api_client:
            await self.api_client.close()

    async def add_part(self, part_data: dict) -> None:
        """Add a new part to InvenTree."""
        try:
            _LOGGER.debug("Creating new part with data: %s", part_data)
            
            # Remove None values
            cleaned_data = {k: v for k, v in part_data.items() if v is not None}
            
            # Call API to create part
            await self.api_client.create_part(cleaned_data)
            
            # Refresh data
            await self.async_refresh()
            
            _LOGGER.debug("Successfully created part: %s", part_data.get("name"))
            
        except Exception as err:
            _LOGGER.error("Error creating part: %s", err)
            raise HomeAssistantError(f"Failed to create part: {err}") from err

    async def get_category(self, category_id: int) -> dict:
        """Get category details."""
        url = f"{self.api_client.api_url}/api/part/category/{category_id}/"
        try:
            async with self.api_client.session.get(
                url,
                headers={"Authorization": f"Token {self.api_client.api_key}"}
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            _LOGGER.error(f"Error getting category {category_id}: {e}")
            raise

    async def get_part_with_hierarchy(self, part_id: int) -> dict:
        """Get part details including category hierarchy."""
        try:
            # Get part details
            url = f"{self.api_client.api_url}/api/part/{part_id}/"
            async with self.api_client.session.get(
                url,
                headers={"Authorization": f"Token {self.api_client.api_key}"}
            ) as response:
                response.raise_for_status()
                part = await response.json()
                
            # Get category hierarchy
            category = await self.get_category(part["category"])
            
            # Add pathstring and URLs
            part["category_pathstring"] = category["pathstring"]
            part["dashboard_url"] = f"/dashboard-{category['pathstring'].lower().replace('/', '/')}"
            part["inventree_url"] = f"/part/{part_id}/"
            
            return part
        except Exception as e:
            _LOGGER.error(f"Error getting part with hierarchy {part_id}: {e}")
            raise

    async def find_barcode(self, barcode: str) -> dict:
        """Find a barcode in InvenTree."""
        url = f"{self.api_client.api_url}/api/barcode/"
        params = {"barcode": barcode}
        try:
            async with self.api_client.session.get(
                url,
                headers={"Authorization": f"Token {self.api_client.api_key}"},
                params=params
            ) as response:
                response.raise_for_status()
                data = await response.json()
                return data if data else None
        except Exception as e:
            _LOGGER.error(f"Error finding barcode: {e}")
            raise

    async def link_barcode(self, part_id: int, barcode: str) -> dict:
        """Link a barcode to a part."""
        url = f"{self.api_client.api_url}/api/barcode/link/"
        data = {
            "part": part_id,
            "barcode": barcode
        }
        try:
            async with self.api_client.session.post(
                url,
                headers={"Authorization": f"Token {self.api_client.api_key}"},
                json=data
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            _LOGGER.error(f"Error linking barcode: {e}")
            raise

    async def process_barcode(self, barcode: str, **kwargs) -> dict:
        """Process a barcode scan and handle part creation."""
        try:
            _LOGGER.debug(f"Processing barcode: {barcode}")
            
            # First check if barcode exists
            url = f"{self.api_client.api_url}/api/barcode/"
            async with self.api_client.session.post(
                url,
                headers={
                    "Authorization": f"Token {self.api_client.api_key}",
                    "Content-Type": "application/json"
                },
                json={"barcode": barcode}
            ) as response:
                data = await response.json()
                _LOGGER.debug(f"Barcode lookup response: {data}")

                if response.status == 200 and data.get('success') == "Match found for barcode data":
                    # Get full part details with hierarchy
                    part = await self.get_part_with_hierarchy(data['part']['pk'])
                    return {
                        "found": True,
                        "part": part,
                        "dashboard_url": part.get("dashboard_url", "/dashboard-uncategorized")
                    }
                
                # Barcode not found, create new part if auto_create is True
                if kwargs.get("auto_create", True):
                    _LOGGER.info("Creating new part for unrecognized barcode")
                    
                    # Create new part
                    new_part_data = {
                        "name": kwargs.get("name", f"Scanned Item {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"),
                        "description": kwargs.get("description", "Automatically created from barcode scan"),
                        "category": kwargs.get("uncategorized_category_id", 125),
                        "units": kwargs.get("units", "pcs"),
                        "active": True
                    }
                    
                    # Use existing add_part method
                    new_part = await self.add_part(new_part_data)
                    
                    if new_part:
                        _LOGGER.info(f"Created new part: {new_part.get('name')}")
                        
                        # Link the barcode to the new part
                        await self.link_barcode(new_part["pk"], barcode)
                        
                        # Get full part details with hierarchy
                        part = await self.get_part_with_hierarchy(new_part["pk"])
                        
                        return {
                            "found": True,
                            "part": part,
                            "dashboard_url": kwargs.get("redirect_to_dashboard", "/dashboard-uncategorized"),
                            "newly_created": True
                        }
                
                return {
                    "found": False,
                    "error": "Barcode not found and auto-create disabled",
                    "barcode_hash": data.get("barcode_hash"),
                    "barcode_data": data.get("barcode_data")
                }
                
        except Exception as e:
            _LOGGER.error(f"Error processing barcode: {e}")
            raise UpdateFailed(f"Error processing barcode: {e}")