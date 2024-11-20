"""Sensor platform for Inventree integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InventreeDataUpdateCoordinator
from .models import CategoryMapping

_LOGGER = logging.getLogger(__name__)

class InventreeBaseSensor(CoordinatorEntity[InventreeDataUpdateCoordinator], SensorEntity):
    """Base class for Inventree sensors."""

    def __init__(
        self, 
        coordinator: InventreeDataUpdateCoordinator, 
        name: str, 
        key: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = f"Inventree {name}"
        self._attr_unique_id = f"inventree_{key}"
        self._key = key
        self._attr_device_class = SensorDeviceClass.ENUM

class InventreePartSensor(InventreeBaseSensor):
    """Sensor for individual parts."""

    def __init__(
        self,
        coordinator: InventreeDataUpdateCoordinator,
        part_data: dict
    ) -> None:
        """Initialize the part sensor."""
        super().__init__(
            coordinator,
            part_data['name'],
            f"part_{part_data['id']}"
        )
        self._part_id = part_data['id']
        self._part_data = part_data

    @property
    def native_value(self) -> int:
        """Return the current stock level."""
        if not self.coordinator.data or "parts" not in self.coordinator.data:
            return 0
        
        part = next(
            (p for p in self.coordinator.data["parts"] 
             if p.get('id') == self._part_id),
            None
        )
        return int(part['stock']) if part else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "parts" not in self.coordinator.data:
            return {}

        part = next(
            (p for p in self.coordinator.data["parts"] 
             if p.get('id') == self._part_id),
            self._part_data
        )
        
        return {
            'name': part['name'],
            'category_path': part['category_path'],
            'item_id': str(part['id']),
            'image_url': part.get('image_url'),
            'description': part.get('description', ''),
            'minimum_stock': part.get('minimum_stock', 0)
        }

class InventreeCategoryStockSensor(InventreeBaseSensor):
    """Sensor for stock in a category."""

    def __init__(
        self, 
        coordinator: InventreeDataUpdateCoordinator,
        category_path: str,
        category_name: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            f"{category_name} Stock",
            f"category_{category_name.lower().replace(' ', '_')}_stock"
        )
        self._category_path = category_path
        self._category_name = category_name

    @property
    def native_value(self) -> int:
        """Return the total stock in category."""
        if not self.coordinator.data or "parts" not in self.coordinator.data:
            return 0
        
        total_stock = sum(
            int(part['stock'])
            for part in self.coordinator.data["parts"]
            if part.get('category_path') == self._category_path
        )
        return total_stock

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "items" not in self.coordinator.data:
            return {}

        _LOGGER.debug("Processing items for attributes: %s", self.coordinator.data["items"])  # Debug log

        items = []
        for item in self.coordinator.data["items"]:
            if isinstance(item, dict) and item.get('category') == self._category_id:
                _LOGGER.debug("Processing item: %s", item)  # Debug log for each matching item
                items.append({
                    'name': item.get('name', ''),
                    'in_stock': item.get('in_stock', 0),
                    'minimum_stock': item.get('minimum_stock', 0),
                    'item_id': item.get('pk'),  # Try pk
                    'part_id': item.get('id'),  # Try id
                    'uid': item.get('uid'),     # Try uid
                })
        
        _LOGGER.debug("Final processed items: %s", items)  # Debug log final result
        
        return {
            'items': items,
            'category_name': self._category_name,
            'category_id': self._category_id
        }

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inventree sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Wait for first update
    await coordinator.async_config_entry_first_refresh()
    
    entities = []
    
    # Add part sensors
    if coordinator.data and "parts" in coordinator.data:
        for part in coordinator.data["parts"]:
            try:
                sensor = InventreePartSensor(coordinator, part)
                entities.append(sensor)
            except Exception as e:
                _LOGGER.error(
                    "Failed to create sensor for part: %s. Error: %s",
                    part.get('name', 'Unknown'),
                    str(e)
                )
    
    # Add category sensors
    categories = {
        "Electronics/Connectors and Wires": "Connectors and Wires",
        "Electronics/LEDs and Displays": "LEDs and Displays",
        "Electronics/Microcontrollers": "Microcontrollers",
        "Electronics/Motors and Drivers": "Motors and Drivers",
        "Electronics/Passive Components": "Passive Components",
        "Electronics/Power Supply": "Power Supply",
        "Electronics/Sensors and Modules": "Sensors and Modules",
        "Electronics/Storage Devices": "Storage Devices"
    }
    
    for category_path, category_name in categories.items():
        entities.append(
            InventreeCategoryStockSensor(
                coordinator,
                category_path,
                category_name
            )
        )
    
    async_add_entities(entities, True) 
 