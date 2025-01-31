"""The Inventree integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import DOMAIN, CONF_API_URL, CONF_API_KEY
from .coordinator import InventreeDataUpdateCoordinator
from .api import InventreeAPIClient

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
        
        # Create and store coordinator
        coordinator = InventreeDataUpdateCoordinator(hass, api_client)
        await coordinator.async_config_entry_first_refresh()
        
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
                # Find base template part
                base_results = await api_client._api_request(f"part/?name={name}")
                base_part = next(
                    (p for p in base_results if p.get('name') == name and p.get('is_template')),
                    None
                )
                
                if not base_part:
                    raise ValueError(f"Template part '{name}' not found")
                    
                base_id = base_part['pk']
                _LOGGER.debug("Found template part: %s (ID: %s)", name, base_id)
                
                # Get variants
                variants = await api_client._api_request(f"part/?variant_of={base_id}")
                
                if operation == "transfer_stock":
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
                        params = await api_client._api_request(f"part/parameter/?part={base_id}")
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
                    
                    # Update parameter on base template
                    await api_client.update_parameter(base_id, parameter_name, parameter_value)
                    
                    _LOGGER.debug(
                        "Updated parameter %s=%s on template %s",
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
            include_images = call.data.get('include_images', True)
            force_update = call.data.get('force_update', False)
            
            _LOGGER.debug("Updating metadata: category=%s, part=%s, images=%s, force=%s",
                         category_id, part_id, include_images, force_update)
            
            try:
                if part_id:
                    # Update single part
                    data = await api_client.get_part_details(
                        part_id=int(part_id),
                        include_images=include_images
                    )
                    _LOGGER.debug("Updated metadata for part %s", part_id)
                elif category_id:
                    # Update all parts in category
                    parts = await api_client.get_category_parts(category_id)
                    for part in parts:
                        if include_images or force_update:
                            data = await api_client.get_part_details(
                                part_id=part['id'],
                                include_images=include_images
                            )
                    _LOGGER.debug("Updated metadata for category %s", category_id)
                else:
                    # Update all parts
                    parts = await api_client.get_items()
                    for part in parts:
                        if include_images or force_update:
                            data = await api_client.get_part_details(
                                part_id=part['pk'],
                                include_images=include_images
                            )
                    _LOGGER.debug("Updated metadata for all parts")

                await coordinator.async_request_refresh()
                
            except Exception as err:
                _LOGGER.error("Failed to update metadata: %s", err)
                raise
        
        # Register services
        hass.services.async_register(DOMAIN, 'add_item', add_item)
        hass.services.async_register(DOMAIN, 'edit_item', edit_item)
        hass.services.async_register(DOMAIN, 'remove_item', remove_item)
        hass.services.async_register(DOMAIN, 'adjust_stock', adjust_stock)
        hass.services.async_register(DOMAIN, 'variant_operations', variant_operations)
        hass.services.async_register(DOMAIN, 'update_metadata', update_metadata)
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