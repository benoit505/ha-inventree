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

class InventreeCategoryStockSensor(InventreeBaseSensor):
    """Sensor for stock in a category."""

    def __init__(
        self, 
        coordinator: InventreeDataUpdateCoordinator,
        category_id: int,
        category_name: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            f"{category_name} Stock",
            f"category_{category_id}_stock"
        )
        self._category_id = category_id
        self._category_name = category_name

    @property
    def native_value(self) -> int:
        """Return the state of the sensor."""
        if not self.coordinator.data or "items" not in self.coordinator.data:
            return 0
        
        total_stock = 0
        for item in self.coordinator.data["items"]:
            if isinstance(item, dict) and item.get('category') == self._category_id:
                total_stock += float(item.get('in_stock', 0))
        return int(total_stock)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "items" not in self.coordinator.data:
            return {}

        items = []
        parameters = self.coordinator.data.get("parameters", {})
        metadata = self.coordinator.data.get("metadata", {})
        
        for item in self.coordinator.data["items"]:
            if isinstance(item, dict) and item.get('category') == self._category_id:
                item_data = {
                    'pk': item.get('pk'),
                    'name': item.get('name', ''),
                    'in_stock': item.get('in_stock', 0),
                    'minimum_stock': item.get('minimum_stock', 0),
                    'image': item.get('image'),
                    'thumbnail': item.get('thumbnail'),
                    'active': item.get('active'),
                    'assembly': item.get('assembly'),
                    'category': item.get('category'),
                    'category_name': item.get('category_name'),
                    'component': item.get('component'),
                    'description': item.get('description'),
                    'full_name': item.get('full_name'),
                    'IPN': item.get('IPN'),
                    'keywords': item.get('keywords'),
                    'purchaseable': item.get('purchaseable'),
                    'revision': item.get('revision'),
                    'salable': item.get('salable'),
                    'units': item.get('units'),
                    'total_in_stock': item.get('total_in_stock'),
                    'unallocated_stock': item.get('unallocated_stock'),
                    'allocated_to_build_orders': item.get('allocated_to_build_orders'),
                    'allocated_to_sales_orders': item.get('allocated_to_sales_orders'),
                    'building': item.get('building'),
                    'ordering': item.get('ordering')
                }
                

                items.append(item_data)
        
        return {
            'items': items,
            'category_name': self._category_name,
            'category_id': self._category_id
        }

class InventreeLowStockSensor(InventreeBaseSensor):
    """Sensor for items with low stock."""

    def __init__(self, coordinator: InventreeDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "Low Stock Items", "low_stock_items")

    @property
    def native_value(self) -> int:
        """Return the number of items with low stock."""
        if not self.coordinator.data or "items" not in self.coordinator.data:
            return 0
        
        low_stock_count = 0
        for item in self.coordinator.data["items"]:
            if isinstance(item, dict):
                in_stock = float(item.get('in_stock', 0))
                min_stock = float(item.get('minimum_stock', 0))
                if in_stock == 0 or (min_stock > 0 and in_stock <= min_stock):
                    low_stock_count += 1
        return low_stock_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the list of items with low stock."""
        if not self.coordinator.data or "items" not in self.coordinator.data:
            return {}

        low_stock_items = []
        for item in self.coordinator.data["items"]:
            if isinstance(item, dict):
                in_stock = float(item.get('in_stock', 0))
                min_stock = float(item.get('minimum_stock', 0))
                if in_stock == 0 or (min_stock > 0 and in_stock <= min_stock):
                    low_stock_items.append({
                        'name': item.get('name', ''),
                        'in_stock': in_stock,
                        'minimum_stock': min_stock,
                        'category': item.get('category_name', '')
                    })
        
        return {'items': low_stock_items}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inventree sensor based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    
    if coordinator.data and "categories" in coordinator.data:
        for category in coordinator.data["categories"]:
            if isinstance(category, dict):
                try:
                    sensor = InventreeCategoryStockSensor(
                        coordinator,
                        category['pk'],
                        category['name']
                    )
                    entities.append(sensor)
                except KeyError as e:
                    _LOGGER.error(
                        "Failed to create sensor for category: %s. Missing key: %s", 
                        category, 
                        e
                    )
    
    entities.append(InventreeLowStockSensor(coordinator))
    
    async_add_entities(entities, True)