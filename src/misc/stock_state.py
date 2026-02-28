"""Helpers for normalizing stock-state values across the pipeline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

IN_STOCK = 1
OUT_OF_STOCK = 0
UNKNOWN_STOCK = -1


def coerce_stock_value(value: Any, default: int = UNKNOWN_STOCK) -> int:
    """Normalize any supported stock representation to the internal integer form."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed in {UNKNOWN_STOCK, OUT_OF_STOCK, IN_STOCK}:
        return parsed

    normalized = str(value or "").strip().lower()
    if normalized == "in_stock":
        return IN_STOCK
    if normalized == "out_of_stock":
        return OUT_OF_STOCK
    return default if default in {UNKNOWN_STOCK, OUT_OF_STOCK, IN_STOCK} else UNKNOWN_STOCK


def stock_value_from_record(item: Mapping[str, Any]) -> int:
    """Read stock state from either the current integer field or the legacy string field."""
    if "in_stock" in item:
        return coerce_stock_value(item.get("in_stock"))
    return coerce_stock_value(item.get("stock_status"))


def count_stock_states(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Count stock states in one pass for summaries and stats payloads."""
    counts = {"in_stock": 0, "out_of_stock": 0, "unknown": 0}
    for item in items:
        value = stock_value_from_record(item)
        if value == IN_STOCK:
            counts["in_stock"] += 1
        elif value == OUT_OF_STOCK:
            counts["out_of_stock"] += 1
        else:
            counts["unknown"] += 1
    return counts
