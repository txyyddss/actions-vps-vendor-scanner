"""Shared utilities for site-specific API scanners."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_payload(raw_text: str) -> dict[str, Any]:
    """Parse JSON from raw API response, handling HTML-wrapped responses."""
    text = raw_text.strip()
    if text.startswith("<"):
        match = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1)
        text = text.replace("&quot;", '"').replace("&amp;", "&")
    return json.loads(text)


def build_cycles(price_datas: Any) -> tuple[list[str], str]:
    """Build cycle names and price_raw string from API price data dict."""
    if not isinstance(price_datas, dict):
        return [], ""
    cycles: list[str] = []
    parts: list[str] = []
    for key, value in price_datas.items():
        cycle_name = str(key).replace("_", " ").title()
        cycles.append(cycle_name)
        parts.append(f"{cycle_name}: {value}")
    return cycles, "; ".join(parts)
