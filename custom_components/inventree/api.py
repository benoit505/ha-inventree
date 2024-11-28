import aiohttp
import asyncio
import logging
from typing import Any, Optional
from .models import InventreePart
from asyncio import sleep
from aiohttp import ClientError

_LOGGER = logging.getLogger(__name__)

class InventreeAPIClient:
    def __init__(self, api_url: str, api_key: str):
        """Initialize the API client."""
        self.api_url = api_url.rstrip('/')
        if self.api_url.endswith('/api'):
            self.api_url = self.api_url[:-4]
        self.api_key = api_key
        self.session = None

    async def async_init(self):
        """Create aiohttp session."""
        self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()

    def _get_api_url(self, endpoint: str) -> str:
        """Construct proper API URL."""
        return f"{self.api_url}/api/{endpoint.lstrip('/')}"

    async def get_category_parts(self, category_path: str) -> list[dict]:
        """Get all parts in a specific category."""
        url = self._get_api_url("part/")
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

    async def get_items(self, filters: dict = None):
        """Get all items, optionally filtered."""
        url = self._get_api_url("part/")
        params = filters if filters else {}
        
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
                
                # Process items to include necessary fields
                processed_items = []
                for item in data:
                    processed_items.append({
                        'pk': item['pk'],
                        'name': item['name'],
                        'category': item.get('category'),
                        'category_name': item.get('category_name', ''),
                        'in_stock': float(item.get('in_stock', 0)),
                        'minimum_stock': float(item.get('minimum_stock', 0)),
                        'description': item.get('description', ''),
                    })
                
                _LOGGER.debug("Retrieved %d items", len(processed_items))
                return processed_items
        except Exception as e:
            _LOGGER.error("Error fetching items: %s", e)
            return []

    async def add_item(self, name, category, quantity):
        """Add a new item."""
        url = self._get_api_url("part/")
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
                
                # Now add stock
                stock_url = self._get_api_url("stock/")
                stock_data = {
                    "part": part["pk"],
                    "quantity": quantity,
                    "location": None
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
            _LOGGER.error("Error adding item: %s", err)
            raise

    async def update_item(self, item_id, data):
        """Update an existing item."""
        url = self._get_api_url(f"part/{item_id}/")
        try:
            async with self.session.patch(
                url, 
                json=data,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json"
                }
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as err:
            _LOGGER.error("Error updating item: %s", err)
            raise

    async def remove_item(self, item_id):
        """Remove an item."""
        url = self._get_api_url(f"part/{item_id}/")
        try:
            async with self.session.delete(
                url,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json"
                }
            ) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as err:
            _LOGGER.error("Error removing item: %s", err)
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
        url = self._get_api_url("part/category/")
        _LOGGER.debug("Fetching category tree from URL: %s", url)
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
                
                # Process categories to include necessary fields
                processed_categories = []
                for category in data:
                    processed_categories.append({
                        'pk': category['pk'],
                        'name': category['name'],
                        'description': category.get('description', ''),
                        'parent': category.get('parent'),
                        'level': category.get('level', 0),
                        'part_count': category.get('part_count', 0),
                        'pathstring': category.get('pathstring', ''),
                    })
                
                _LOGGER.debug("Retrieved %d categories", len(processed_categories))
                return processed_categories
        except Exception as err:
            _LOGGER.error("Error fetching category tree: %s", err)
            return []  # Return empty list instead of raising

    async def get_stock_locations(self):
        """Get all stock locations."""
        url = self._get_api_url("stock/location/")
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
                
                # Process locations to include necessary fields
                processed_locations = []
                for location in data:
                    processed_locations.append({
                        'pk': location['pk'],
                        'name': location['name'],
                        'description': location.get('description', ''),
                        'parent': location.get('parent'),
                        'pathstring': location.get('pathstring', ''),
                        'items': location.get('items', 0),
                    })
                
                _LOGGER.debug("Retrieved %d locations", len(processed_locations))
                return processed_locations
        except Exception as err:
            _LOGGER.error("Error fetching stock locations: %s", err)
            return []

    async def get_low_stock_items(self) -> list[InventreePart]:
        """Get all items with stock below minimum level or zero stock."""
        url = self._get_api_url("part/")
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
                if not response.headers.get('content-type', '').startswith('application/json'):
                    _LOGGER.error(
                        "Unexpected content type: %s from URL: %s", 
                        response.headers.get('content-type'), 
                        response.url
                    )
                    return []
                data = await response.json()
                
                parts = []
                for item in data:
                    try:
                        in_stock = float(item.get('in_stock', 0))
                        min_stock = float(item.get('minimum_stock', 0))
                        
                        if in_stock == 0 or (min_stock > 0 and in_stock <= min_stock):
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
                                "Low stock item found: %s (in stock: %s, minimum: %s)",
                                part.name, in_stock, min_stock
                            )
                    except Exception as e:
                        _LOGGER.error("Error processing item %s: %s", item.get('name', 'Unknown'), e)
                        continue
                
                _LOGGER.info("Found %d items with low stock", len(parts))
                return parts
                
        except Exception as err:
            _LOGGER.error("Error fetching low stock items: %s", err)
            return []  # Return empty list instead of raising

    async def add_stock(self, item_id: int, quantity: int, location_id: int = None):
        """Add a quantity of stock to an item."""
        url = self._get_api_url("stock/")
        
        try:
            stock_data = {
                "part": item_id,
                "quantity": quantity,
                "status": 10,
                "delete_on_deplete": True
            }
            if location_id:
                stock_data["location"] = location_id
            
            _LOGGER.debug("Creating stock item with data: %s", stock_data)
            
            async with self.session.post(
                url,
                json=stock_data,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            ) as response:
                response.raise_for_status()
                result = await response.json()
                _LOGGER.debug("Stock item created: %s", result)
                return result
                
        except Exception as err:
            _LOGGER.error("Error adding stock: %s", err)
            raise

    async def remove_stock(self, item_id: int, quantity: int):
        """Remove a quantity of stock from an item."""
        try:
            # First consolidate all stock entries
            await self.consolidate_stock(item_id)
            
            # Get the consolidated stock entry
            stock_url = self._get_api_url("stock/")
            async with self.session.get(
                stock_url,
                params={"part": item_id},
                headers={"Authorization": f"Token {self.api_key}"}
            ) as response:
                response.raise_for_status()
                stock_items = await response.json()
                
                if not stock_items:
                    raise ValueError(f"No stock items found for part {item_id}")
                
                # Should only be one item after consolidation
                stock_item = stock_items[0]
                
                # Remove stock using the correct endpoint
                remove_url = self._get_api_url("stock/remove/")
                async with self.session.post(
                    remove_url,
                    json={
                        "items": [{
                            "pk": stock_item['pk'],
                            "quantity": quantity
                        }]
                    },
                    headers={
                        "Authorization": f"Token {self.api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json"
                    }
                ) as remove_response:
                    remove_response.raise_for_status()
                    return await remove_response.json()

        except Exception as err:
            _LOGGER.error("Error removing stock: %s", err)
            raise

    async def get_part_parameters(self, part_id: int):
        """Get parameters for a specific part."""
        url = f"{self.api_url}/api/part/parameter/"
        params = {"part": part_id}
        
        try:
            _LOGGER.debug("Fetching parameters from URL: %s with params: %s", url, params)
            async with self.session.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            ) as response:
                response.raise_for_status()
                if not response.headers.get('content-type', '').startswith('application/json'):
                    _LOGGER.error(
                        "Unexpected content type: %s from URL: %s", 
                        response.headers.get('content-type'), 
                        response.url
                    )
                    return []
                return await response.json()
        except Exception as e:
            _LOGGER.error("Error fetching part parameters from %s: %s", url, e)
            return []

    async def _api_request(self, endpoint: str, method: str = "GET", data: dict = None, retries: int = 3) -> Any:
        """Make an API request to InvenTree with retries."""
        url = f"{self.api_url}/api/{endpoint}"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        
        for attempt in range(retries):
            try:
                async with self.session.request(method, url, headers=headers, json=data) as response:
                    if response.status == 502:  # Bad Gateway
                        if attempt < retries - 1:
                            await sleep(1 * (attempt + 1))  # Exponential backoff
                            continue
                    response.raise_for_status()
                    return await response.json()
            except ClientError as e:
                if attempt < retries - 1:
                    _LOGGER.warning("API request failed (attempt %d/%d): %s", attempt + 1, retries, e)
                    await sleep(1 * (attempt + 1))
                    continue
                raise

    async def consolidate_stock(self, part_id: int):
        """Consolidate stock entries for a part into a single entry."""
        stock_url = self._get_api_url("stock/")
        
        try:
            # Fetch all stock entries for the part
            async with self.session.get(
                stock_url,
                params={"part": part_id},
                headers={"Authorization": f"Token {self.api_key}"}
            ) as response:
                response.raise_for_status()
                stock_items = await response.json()

            # Calculate total stock
            total_quantity = sum(float(item['quantity']) for item in stock_items)

            # Create a new consolidated entry
            new_entry_data = {
                "part": part_id,
                "quantity": total_quantity,
                "status": 10  # Assuming "OK" status
            }
            async with self.session.post(
                stock_url,
                json=new_entry_data,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            ) as create_response:
                create_response.raise_for_status()
                new_entry = await create_response.json()

            # Delete old entries
            for item in stock_items:
                delete_url = self._get_api_url(f"stock/{item['pk']}/")
                async with self.session.delete(
                    delete_url,
                    headers={"Authorization": f"Token {self.api_key}"}
                ) as delete_response:
                    delete_response.raise_for_status()

            return new_entry

        except Exception as err:
            _LOGGER.error("Error consolidating stock: %s", err)
            raise