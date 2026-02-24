from __future__ import annotations
"""Defines common data structures and types for parser outputs."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedItem:
    """Represents ParsedItem."""
    platform: str
    is_product: bool
    is_category: bool
    in_stock: bool | None
    name_raw: str
    name_en: str
    description_raw: str
    description_en: str
    price_raw: str
    cycles: list[str] = field(default_factory=list)
    locations_raw: list[str] = field(default_factory=list)
    locations_en: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    product_links: list[str] = field(default_factory=list)
    category_links: list[str] = field(default_factory=list)

