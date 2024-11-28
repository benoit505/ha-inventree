import aiohttp
import asyncio
import logging
from typing import Any, Optional
from .models import InventreePart

_LOGGER = logging.getLogger(__name__)

class InventreeAPIClient:
    def __init__(self, api_url: str, api_key: str):
        """Initialize the API client."""
        self.api_url = api_url.rstrip('/')
        # Remove the extra /api if it's already in the url
        if not '/api' in self.api_url:
            self.api_url = f"{self.api_url}/api"
        self.api_key = api_key
        self.session = None

    async def async_init(self):
        """Create aiohttp session."""
        self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()

    async def get_category_parts(self, category_path: str) -> list[dict]:
        """Get all parts in a specific category."""
        url = f"{self.api_url}/part/"
        params = {
            "category_detail": "true",
            "path": category_path
        }
        
        try:
            async with self.session.get(
                url,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json"
                },
                params=params
            ) as response:
                response.raise_for_status()
                parts = await response.json()
                
                # Process each part to get the data we need
                processed_parts = []
                for part in parts:
                    processed_parts.append({
                        'id': part['pk'],
                        'name': part['name'],
                        'category_path': part['category_detail']['pathstring'],
                        'stock': part['in_stock'],
                        'image_url': f"{self.api_url}/media/{part['image']}" if part.get('image') else None,
                        'description': part.get('description', ''),
                        'minimum_stock': part.get('minimum_stock', 0)
                    })
                
                _LOGGER.debug(f"Found {len(processed_parts)} parts in category {category_path}")
                return processed_parts
                
        except Exception as err:
            _LOGGER.error(f"Error fetching category parts: {str(err)}")
            raise

    async def get_items(self):
        """Get all items."""
        url = f"{self.api_url}/part/"
        _LOGGER.debug(f"Fetching items from URL: {url}")
        try:
            async with self.session.get(
                url, 
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json"
                }
            ) as response:
                response.raise_for_status()
                data = await response.json()
                _LOGGER.debug(f"Successfully fetched {len(data)} items")
                return data
        except Exception as err:
            _LOGGER.error(f"Error fetching items: {str(err)}")
            raise

    async def add_item(self, name, category, quantity):
        """Add a new item."""
        url = f"{self.api_url}/part/"
        
        # Create part data according to Inventree's structure
        part_data = {
            "name": name,
            "description": "Added via Home Assistant",
            "category": int(category),
            "active": True,
            "assembly": False,
            "component": True,
            "purchaseable": True,
            "salable": False,
            "trackable": False,
            "virtual": False,
            "units": "",
            "minimum_stock": 0.0,
        }
        
        _LOGGER.debug(f"Creating part with data: {part_data}")
        
        try:
            # First create the part
            async with self.session.post(
                url,
                json=part_data,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json"
                }
            ) as response:
                response.raise_for_status()
                part = await response.json()
                _LOGGER.debug(f"Created part: {part}")
                
                # Now add stock
                stock_url = f"{self.api_url}/stock/"
                stock_data = {
                    "part": part["pk"],
                    "quantity": quantity,
                    "location": None  # Can be updated later
                }
                
                async with self.session.post(
                    stock_url,
                    json=stock_data,
                    headers={
                        "Authorization": f"Token {self.api_key}",
                        "Content-Type": "application/json"
                    }
                ) as stock_response:
                    stock_response.raise_for_status()
                    return await stock_response.json()
        except Exception as err:
            _LOGGER.error(f"Error adding item: {str(err)}")
            raise

    async def update_item(self, item_id, data):
        """Update an existing item."""
        url = f"{self.api_url}/part/{item_id}/"
        _LOGGER.debug(f"Updating item {item_id} at URL: {url}")
        try:
            async with self.session.patch(
                url, 
                json=data,
                headers={"Authorization": f"Token {self.api_key}"}
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as err:
            _LOGGER.error(f"Error updating item: {str(err)}")
            raise

    async def remove_item(self, item_id):
        """Remove an item."""
        url = f"{self.api_url}/part/{item_id}/"
        _LOGGER.debug(f"Removing item {item_id} at URL: {url}")
        try:
            async with self.session.delete(
                url,
                headers={"Authorization": f"Token {self.api_key}"}
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as err:
            _LOGGER.error(f"Error removing item: {str(err)}")
            raise

    async def test_connection(self):
        """Test the connection to Inventree."""
        try:
            await self.get_items()
            return True
        except Exception as e:
            _LOGGER.error(f"Connection test failed: {e}")
            raise

    async def apply_recipe(self, recipe_id):
        """Apply a recipe."""
        url = f"{self.api_url}/recipe/{recipe_id}/apply/"
        _LOGGER.debug(f"Applying recipe {recipe_id} at URL: {url}")
        try:
            async with self.session.post(
                url,
                headers={"Authorization": f"Token {self.api_key}"}
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as err:
            _LOGGER.error(f"Error applying recipe: {str(err)}")
            raise

    async def get_category_tree(self):
        """Get complete category hierarchy from Inventree."""
        url = f"{self.api_url}/part/category/"
        _LOGGER.debug(f"Fetching category tree from URL: {url}")
        try:
            async with self.session.get(
                url, 
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json"
                }
            ) as response:
                response.raise_for_status()
                data = await response.json()
                _LOGGER.debug(f"Retrieved category tree with {len(data)} categories")
                return data
        except Exception as err:
            _LOGGER.error(f"Error fetching category tree: {str(err)}")
            raise

    async def get_stock_locations(self):
        """Get all stock locations."""
        url = f"{self.api_url}/stock/location/"
        try:
            async with self.session.get(
                url,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json"
                }
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as err:
            _LOGGER.error(f"Error fetching stock locations: {str(err)}")
            raise

    async def get_low_stock_items(self) -> list[InventreePart]:
        """Get all items with stock below minimum level or zero stock."""
        url = f"{self.api_url}/part/"
        params = {
            "active": "true",
            "purchaseable": "true"
        }
        
        try:
            async with self.session.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json"
                }
            ) as response:
                response.raise_for_status()
                data = await response.json()
                
                parts = []
                for item in data:
                    in_stock = float(item.get('in_stock', 0))
                    min_stock = float(item.get('minimum_stock', 0))
                    
                    # Include if:
                    # 1. Stock is zero OR
                    # 2. Minimum stock is set and current stock is at or below minimum
                    if (in_stock == 0) or (min_stock > 0 and in_stock <= min_stock):
                        try:
                            part = InventreePart(
                                pk=item['pk'],
                                name=item['name'],
                                description=item.get('description', ''),
                                category=item.get('category'),
                                active=item.get('active', True),
                                assembly=item.get('assembly', False),
                                component=item.get('component', True),
                                in_stock=in_stock,
                                minimum_stock=min_stock,
                                units=item.get('units', ''),
                                category_name=item.get('category_name'),
                                default_location=item.get('default_location')
                            )
                            parts.append(part)
                            _LOGGER.debug(
                                f"Low stock item found: {part.name} "
                                f"(in stock: {in_stock}, minimum: {min_stock})"
                            )
                        except Exception as e:
                            _LOGGER.error(f"Error converting item {item.get('name', 'Unknown')}: {e}")
                            continue
                
                _LOGGER.info(f"Found {len(parts)} items with low stock")
                return parts
                
        except Exception as err:
            _LOGGER.error(f"Error fetching low stock items: {str(err)}")
            raise

    async def add_stock(self, item_id: int, quantity: int, location_id: int = None):
        """Add a quantity of stock to an item."""
        url = f"{self.api_url}/stock/add/"
        
        try:
            stock_data = {
                "item": item_id,
                "quantity": quantity,
                "location": location_id,  # Optional location ID
                "use_pack_size": False,   # Default to individual items, not packs
            }
            
            async with self.session.post(
                url,
                json=stock_data,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json"
                }
            ) as response:
                response.raise_for_status()
                return await response.json()
                
        except Exception as err:
            _LOGGER.error(f"Error adding stock: {str(err)}")
            raise

    async def remove_stock(self, item_id: int, quantity: int, location_id: int = None):
        """Remove a quantity of stock from an item."""
        url = f"{self.api_url}/stock/remove/"
        
        try:
            stock_data = {
                "item": item_id,
                "quantity": quantity,
                "location": location_id,  # Optional location ID
            }
            
            async with self.session.post(
                url,
                json=stock_data,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json"
                }
            ) as response:
                response.raise_for_status()
                return await response.json()
                
        except Exception as err:
            _LOGGER.error(f"Error removing stock: {str(err)}")
            raise

    async def get_part_parameters(self, part_id: int):
        """Get parameters for a specific part."""
        url = f"{self.api_url}/part/parameter/"
        params = {"part": part_id}
        
        try:
            async with self.session.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json"
                }
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            _LOGGER.error("Error fetching part parameters: %s", e)
            return []

    async def _api_request(self, endpoint: str, method: str = "GET", data: dict = None) -> Any:
        """Make an API request to InvenTree."""
        url = f"{self.api_url}/api/{endpoint}"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with self.session.request(method, url, headers=headers, json=data) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            _LOGGER.error("API request failed: %s", e)
            raise