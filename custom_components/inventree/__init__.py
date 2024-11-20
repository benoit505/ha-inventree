"""The Inventree integration."""
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, CONF_API_URL, CONF_API_KEY
from .coordinator import InventreeDataUpdateCoordinator
from .api import InventreeAPIClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]

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
                # Get the current state
                sensor = hass.states.get("sensor.inventree_microcontrollers_stock")
                if not sensor:
                    raise ValueError("Sensor not found")
                    
                items = sensor.attributes.get("items", [])
                _LOGGER.debug("Found items in sensor: %s", items)
                
                for item in items:
                    _LOGGER.debug("Checking item: %s", item)
                    if item["name"] == name:
                        _LOGGER.debug("Found matching item: %s", item)
                        item_id = item.get("item_id")
                        if not item_id:
                            raise ValueError(f"No item_id found for {name}")
                            
                        _LOGGER.debug("Using item_id: %s", item_id)
                        
                        if quantity > 0:
                            _LOGGER.debug("Adding %s to stock for item %s", quantity, item_id)
                            await api_client.add_stock(item_id=item_id, quantity=quantity)
                        else:
                            _LOGGER.debug("Removing %s from stock for item %s", abs(quantity), item_id)
                            await api_client.remove_stock(item_id=item_id, quantity=abs(quantity))
                            
                        await coordinator.async_request_refresh()
                        return
                        
                raise ValueError(f"Item {name} not found")
                    
            except Exception as err:
                _LOGGER.error("Failed to adjust stock: %s", err)
                _LOGGER.exception("Full error:")  # This will log the full stack trace
        
        # Register services
        hass.services.async_register(DOMAIN, 'add_item', add_item)
        hass.services.async_register(DOMAIN, 'edit_item', edit_item)
        hass.services.async_register(DOMAIN, 'remove_item', remove_item)
        hass.services.async_register(DOMAIN, 'adjust_stock', adjust_stock)
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