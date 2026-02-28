from __future__ import annotations
"""Defines common data structures and types for parser outputs."""

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedItem:
    """Represents ParsedItem."""
    platform: str
    is_product: bool
    is_category: bool
    in_stock: bool | None
    name_raw: str
    description_raw: str
    price_raw: str
    cycles: list[str] = field(default_factory=list)
    locations_raw: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    product_links: list[str] = field(default_factory=list)
    category_links: list[str] = field(default_factory=list)


def in_stock_int(flag: bool | None) -> int:
    """Convert parser bool|None to integer: 1=in_stock, 0=oos, -1=unknown."""
    if flag is True:
        return 1
    if flag is False:
        return 0
    return -1


def bs4_text(node: object) -> str:
    """Extract text from a BeautifulSoup node."""
    return str(node.get_text("\n", strip=True)) if hasattr(node, "get_text") else ""


def extract_prices(text: str) -> list[str]:
    """Extract price strings from text."""
    return list(dict.fromkeys(re.findall(r"(?:[$€£¥]|HK\$)\s?[0-9][0-9,.]*\s?(?:USD|CAD|HKD)?", text)))
