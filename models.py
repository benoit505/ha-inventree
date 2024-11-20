"""Data models for Inventree integration."""
from dataclasses import dataclass
from typing import Optional

@dataclass
class InventreePart:
    """Class representing an Inventree Part."""
    pk: int
    name: str
    description: Optional[str] = None
    category: Optional[int] = None
    active: bool = True
    assembly: bool = False
    component: bool = True
    in_stock: float = 0.0
    minimum_stock: float = 0.0
    units: str = ""
    category_name: Optional[str] = None
    default_location: Optional[int] = None

@dataclass
class CategoryMapping:
    """Class to map category IDs to names."""
    id: int
    name: str
    parent_id: Optional[int] = None 