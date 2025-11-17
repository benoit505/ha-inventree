"""The Inventree integration."""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import DOMAIN, CONF_API_URL, CONF_API_KEY, CONF_WEBSOCKET_URL, CONF_ENABLE_WEBSOCKET, DEFAULT_WEBSOCKET_PORT
from .coordinator_v2 import SmartInventreeCoordinator
from .api import InventreeAPIClient
from urllib.parse import urlparse

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]

# Updated schema definition
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Inventree integration from YAML."""
    _LOGGER.debug("Setting up Inventree integration")
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Inventree from a config entry."""
    _LOGGER.debug("Starting async_setup_entry for Inventree with entry_id: %s", entry.entry_id)
    
    try:
        api_client = InventreeAPIClient(
            entry.data[CONF_API_URL], 
            entry.data[CONF_API_KEY]
        )
        await api_client.async_init()
        
        # Determine WebSocket URL
        websocket_url = entry.data.get(CONF_WEBSOCKET_URL, "")
        enable_websocket = entry.data.get(CONF_ENABLE_WEBSOCKET, True)
        
        # Auto-generate WebSocket URL if not provided
        if not websocket_url and enable_websocket:
            parsed = urlparse(entry.data[CONF_API_URL])
            # Use ws:// for http and wss:// for https
            ws_scheme = "ws" if parsed.scheme == "http" else "wss"
            websocket_url = f"{ws_scheme}://{parsed.hostname}:{DEFAULT_WEBSOCKET_PORT}"
            _LOGGER.info("Auto-generated WebSocket URL: %s", websocket_url)
        
        # Create and store smart coordinator
        coordinator = SmartInventreeCoordinator(
            hass,
            api_client,
            websocket_url=websocket_url if websocket_url else None,
            enable_websocket=enable_websocket and bool(websocket_url)
        )
        
        # Start coordinator (includes WebSocket)
        await coordinator.async_start()
        
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = coordinator
        
        # Setup platforms using async_forward_entry_setups
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        # Register services
        async def add_item(call) -> None:
            """Handle adding an item."""
            name = call.data.get('name')
            category = call.data.get('category')
            quantity = call.data.get('quantity')
            _LOGGER.debug("Adding item: %s in category %s with quantity %s", 
                         name, category, quantity)
            try:
                await api_client.add_item(name, category, quantity)
                await coordinator.async_request_refresh()
            except Exception as err:
                _LOGGER.error("Failed to add item: %s", err)
        
        async def edit_item(call) -> None:
            """Handle editing an item."""
            item_id = call.data.get('item_id')
            data = {k: v for k, v in call.data.items() if k != 'item_id'}
            _LOGGER.debug("Editing item %s with data: %s", item_id, data)
            try:
                await api_client.update_item(item_id, data)
                await coordinator.async_request_refresh()
            except Exception as err:
                _LOGGER.error("Failed to edit item: %s", err)
        
        async def remove_item(call) -> None:
            """Handle removing an item."""
            item_id = call.data.get('item_id')
            _LOGGER.debug("Removing item: %s", item_id)
            try:
                await api_client.remove_item(item_id)
                await coordinator.async_request_refresh()
            except Exception as err:
                _LOGGER.error("Failed to remove item: %s", err)

        async def adjust_stock(call) -> None:
            """Handle adjusting stock levels."""
            name = call.data.get('name')
            quantity = call.data.get('quantity', 0)
            _LOGGER.debug("Adjusting stock for %s by %s", name, quantity)
            
            try:
                # Search for the item directly via API
                search_url = f"part/?search={name}"
                search_results = await api_client._api_request(search_url)
                
                if not search_results:
                    raise ValueError(f"Item '{name}' not found")
                    
                # Use the first matching result
                item = search_results[0]
                part_id = item.get('pk')
                
                if not part_id:
                    raise ValueError(f"Invalid item data received for '{name}'")
                    
                _LOGGER.debug("Found item: %s (ID: %s)", item.get('name'), part_id)
                
                if quantity > 0:
                    await api_client.add_stock(item_id=part_id, quantity=quantity)
                else:
                    await api_client.remove_stock(item_id=part_id, quantity=abs(quantity))
                    
                await coordinator.async_request_refresh()
                    
            except Exception as err:
                _LOGGER.error("Failed to adjust stock: %s", err)
                raise
        
        async def variant_operations(call: ServiceCall) -> None:
            """Handle variant operations."""
            name = call.data.get('name')
            operation = call.data.get('operation')
            
            try:
                # Find part by name (could be template or regular part)
                search_results = await api_client._api_request(f"part/?name={name}")
                
                # Find exact match by name
                part = next((p for p in search_results if p.get('name', '').lower() == name.lower()), None)
                
                if not part:
                    raise ValueError(f"Part '{name}' not found")
                    
                part_id = part['pk']
                is_template = part.get('is_template', False)
                
                _LOGGER.debug("Found part: %s (ID: %s, is_template: %s)", name, part_id, is_template)
                
                if operation == "transfer_stock" and is_template:
                    # Get variants - only works for template parts
                    variants = await api_client._api_request(f"part/?variant_of={part_id}")
                    
                    source_name = call.data.get('source_variant')
                    target_name = call.data.get('target_variant')
                    quantity = float(call.data.get('quantity', 0))
                    
                    # Find source and target variants
                    source_variant = next((v for v in variants if v['name'] == source_name), None)
                    target_variant = next((v for v in variants if v['name'] == target_name), None)
                    
                    if not source_variant or not target_variant:
                        raise ValueError(f"Could not find variants: {source_name} -> {target_name}")
                        
                    # Handle special case for Raw->Prepared conversion
                    if "Raw" in source_name and "Cooked" in target_name:
                        # Get cooked ratio parameter
                        params = await api_client._api_request(f"part/parameter/?part={part_id}")
                        cooked_ratio = next(
                            (float(p['data']) for p in params if p['template_detail']['name'] == 'Cooked_Ratio'),
                            1.0
                        )
                        target_quantity = quantity * cooked_ratio
                    else:
                        target_quantity = quantity
                    
                    # Perform the transfer
                    await api_client.remove_stock(source_variant['pk'], quantity)
                    await api_client.add_stock(target_variant['pk'], target_quantity)
                    
                    _LOGGER.debug(
                        "Transferred stock: %s -> %s (quantity: %s -> %s)",
                        source_name, target_name, quantity, target_quantity
                    )
                    
                elif operation == "update_parameter":
                    parameter_name = call.data.get('parameter_name')
                    parameter_value = call.data.get('parameter_value')
                    
                    # Update parameter on the part (template or regular)
                    await api_client.update_parameter(part_id, parameter_name, parameter_value)
                    
                    _LOGGER.debug(
                        "Updated parameter %s=%s on part %s",
                        parameter_name, parameter_value, name
                    )
                    
                elif operation == "manage_batch":
                    # Future implementation
                    _LOGGER.info("Batch management not yet implemented")
                    
                else:
                    raise ValueError(f"Unknown operation: {operation}")
                    
                await coordinator.async_refresh()
                
            except Exception as err:
                _LOGGER.error("Failed to perform variant operation: %s", err)
                raise
        
        async def update_metadata(call) -> None:
            """Handle metadata updates."""
            category_id = call.data.get('category_id')
            part_id = call.data.get('part_id')
            download_thumbnails = call.data.get('download_thumbnails', True)
            force_update = call.data.get('force_update', False)
            parameter_name = call.data.get('parameter_name')
            force_thumbnail_update = call.data.get('force_thumbnail_update', False)
            
            _LOGGER.debug("Updating metadata: category=%s, part=%s, thumbnails=%s, force=%s, parameter=%s, force_thumbnails=%s",
                         category_id, part_id, download_thumbnails, force_update, parameter_name, force_thumbnail_update)
            
            try:
                if part_id:
                    # Update single part
                    data = await api_client.update_metadata(
                        part_id=int(part_id),
                        download_thumbnails=download_thumbnails and (force_thumbnail_update or force_update),
                        parameter_name=parameter_name
                    )
                    _LOGGER.debug("Updated metadata for part %s", part_id)
                elif category_id:
                    # Update all parts in category
                    parts = await api_client.get_category_parts(category_id)
                    for part in parts:
                        if download_thumbnails or force_update:
                            data = await api_client.update_metadata(
                                part_id=part['id'],
                                download_thumbnails=download_thumbnails and (force_thumbnail_update or force_update),
                                parameter_name=parameter_name
                            )
                    _LOGGER.debug("Updated metadata for category %s", category_id)
                else:
                    # Update all parts
                    parts = await api_client.get_items()
                    for part in parts:
                        if download_thumbnails or force_update:
                            data = await api_client.update_metadata(
                                part_id=part['pk'],
                                download_thumbnails=download_thumbnails and (force_thumbnail_update or force_update),
                                parameter_name=parameter_name
                            )
                    _LOGGER.debug("Updated metadata for all parts")

                await coordinator.async_request_refresh()
                
            except Exception as err:
                _LOGGER.error("Failed to update metadata: %s", err)
                raise
        
        async def print_label(call) -> None:
            """Handle printing a label."""
            item_id = call.data.get('item_id')
            template_id = call.data.get('template_id', 2)
            plugin = call.data.get('plugin', 'zebra')
            
            _LOGGER.debug("Printing label for item %s using template %s and plugin %s", 
                         item_id, template_id, plugin)
            try:
                # Get the coordinator
                coordinator = hass.data[DOMAIN][entry.entry_id]
                await coordinator.api_client.print_label(
                    item_id=int(item_id),
                    template_id=int(template_id),
                    plugin=plugin
                )
                _LOGGER.debug("Label printed successfully")
            except Exception as err:
                _LOGGER.error("Failed to print label: %s", err)
                raise
        
        async def update_parameter(call) -> None:
            """Handle updating a parameter."""
            part_id = call.data.get('part_id')
            parameter_name = call.data.get('parameter_name')
            value = call.data.get('value')
            
            _LOGGER.debug("Updating parameter %s=%s for part %s",
                         parameter_name, value, part_id)
            
            try:
                await api_client.update_parameter(part_id, parameter_name, value)
                await coordinator.async_request_refresh()
                _LOGGER.debug("Parameter updated successfully")
            except Exception as err:
                _LOGGER.error("Failed to update parameter: %s", err)
                raise
        
        async def get_coordinator_stats(call) -> None:
            """Get coordinator statistics."""
            stats = coordinator.get_stats()
            _LOGGER.info("=== InvenTree Coordinator Statistics ===")
            _LOGGER.info("Full updates: %d", stats['full_updates'])
            _LOGGER.info("Partial updates: %d", stats['partial_updates'])
            _LOGGER.info("WebSocket events: %d", stats['websocket_events'])
            _LOGGER.info("Cached parts: %d", stats['cached_parts'])
            _LOGGER.info("Cached categories: %d", stats['cached_categories'])
            _LOGGER.info("WebSocket enabled: %s", stats['websocket_enabled'])
            if stats['websocket_enabled']:
                _LOGGER.info("WebSocket connected: %s", stats.get('connected'))
                _LOGGER.info("Activity state: %s", stats.get('activity_state'))
                _LOGGER.info("Poll interval: %ss", stats.get('poll_interval_seconds'))
            _LOGGER.info("======================================")
        
        # Register services
        hass.services.async_register(DOMAIN, 'add_item', add_item)
        hass.services.async_register(DOMAIN, 'edit_item', edit_item)
        hass.services.async_register(DOMAIN, 'remove_item', remove_item)
        hass.services.async_register(DOMAIN, 'adjust_stock', adjust_stock)
        hass.services.async_register(DOMAIN, 'variant_operations', variant_operations)
        hass.services.async_register(DOMAIN, 'update_metadata', update_metadata)
        hass.services.async_register(DOMAIN, 'update_parameter', update_parameter)
        hass.services.async_register(DOMAIN, 'print_label', print_label)
        hass.services.async_register(DOMAIN, 'get_stats', get_coordinator_stats)

        # Register service
        async def handle_add_part(call: ServiceCall) -> None:
            """Handle the add_part service call."""
            await coordinator.add_part(call.data)

        async def async_process_barcode(hass: HomeAssistant, coordinator: InventreeDataUpdateCoordinator, barcode: str, **kwargs) -> dict:
            """Process a barcode scan."""
            try:
                # Process barcode using API
                result = await coordinator.api_client.process_barcode(barcode)
                
                if not result.get("found", False):
                    _LOGGER.info(f"Barcode not found: {result.get('error')}")
                    
                    # If auto_create is True, create a new part
                    if kwargs.get("auto_create", True):
                        _LOGGER.info("Creating new part for unrecognized barcode")
                        
                        # Set default values if not provided
                        name = kwargs.get("name")
                        if not name:
                            name = f"Scanned Item {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        description = kwargs.get("description")
                        if not description:
                            description = f"Automatically created from barcode scan on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        new_part = await coordinator.api_client.create_part({
                            "name": name,
                            "description": description,
                            "category": kwargs.get("uncategorized_category_id", 125),
                            "units": kwargs.get("units", "pcs"),
                            "active": True,
                            "component": True,
                            "assembly": False,
                            "purchaseable": True,
                            "salable": False,
                            "trackable": True,
                            "virtual": False
                        })
                        
                        if new_part:
                            _LOGGER.info(f"Created new part: {new_part.get('name')}")
                            # Link the barcode to the new part
                            await coordinator.api_client.link_barcode(barcode, new_part["pk"])
                            
                            return {
                                "found": True,
                                "part": new_part,
                                "dashboard_url": kwargs.get("redirect_to_dashboard", "/dashboard-uncategorized"),
                                "newly_created": True
                            }
                    
                    return {
                        "found": False,
                        "error": result.get("error"),
                        "barcode_hash": result.get("barcode_hash"),
                        "barcode_data": result.get("barcode_data")
                    }
                
                # Part was found
                new_part = result.get("part")
                if new_part:
                    return {
                        "found": True,
                        "part": new_part,
                        "dashboard_url": result.get("dashboard_url")
                    }
                
                return {
                    "found": False,
                    "error": "No part information available"
                }
                    
            except Exception as e:
                _LOGGER.error(f"Error processing barcode: {e}")
                raise

        async def process_barcode(call: ServiceCall) -> None:
            """Handle the service call."""
            barcode = call.data.get("barcode")
            # Pass through all the optional parameters
            result = await async_process_barcode(
                hass, 
                coordinator, 
                barcode,
                name=call.data.get("name"),
                description=call.data.get("description"),
                units=call.data.get("units"),
                uncategorized_category_id=call.data.get("uncategorized_category_id"),
                auto_create=call.data.get("auto_create"),
                redirect_to_dashboard=call.data.get("redirect_to_dashboard")
            )

        hass.services.async_register(
            DOMAIN,
            "process_barcode",
            process_barcode,
            schema=vol.Schema({
                vol.Required("barcode"): str,
                vol.Optional("name"): str,
                vol.Optional("description"): str,
                vol.Optional("units", default="pcs"): str,
                vol.Optional("uncategorized_category_id", default=125): int,
                vol.Optional("auto_create", default=True): bool,
                vol.Optional("redirect_to_dashboard", default="/dashboard-uncategorized"): str,
            })
        )

        _LOGGER.debug("Services registered successfully")
        
        return True
        
    except Exception as err:
        _LOGGER.error("Failed to connect to Inventree API: %s", err)
        raise ConfigEntryNotReady from err

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.entry_id)
    
    # Close the API client session
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator and coordinator.api_client:
        await coordinator.api_client.close()
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.debug("Reloading entry: %s", entry.entry_id)
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)