"""Validates live stock status for products against their latest webpage state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.misc.config_loader import coerce_positive_int, dump_json, load_json
from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.stock_state import count_stock_states, stock_value_from_record
from src.parsers.hostbill_parser import parse_hostbill_page
from src.parsers.whmcs_parser import parse_whmcs_page


@dataclass(slots=True)
class StockSyncResult:
    """Represents a full stock snapshot refresh outcome."""

    products: list[dict[str, Any]]
    snapshot_items: list[dict[str, Any]]
    checked_items: list[dict[str, Any]]
    changed_items: list[dict[str, Any]]


def _stock_key(item: dict[str, Any]) -> str:
    """Return the canonical lookup key used for stock snapshots."""
    return str(item.get("canonical_url") or item.get("source_url") or "")


def _snapshot_from_product(item: dict[str, Any]) -> dict[str, Any]:
    """Project a product record into the persisted stock snapshot shape."""
    snapshot: dict[str, Any] = {
        "product_id": item.get("product_id"),
        "canonical_url": _stock_key(item),
        "site": item.get("site", ""),
        "name_raw": item.get("name_raw", ""),
        "in_stock": stock_value_from_record(item),
        "checked_at": item.get("checked_at"),
        "evidence": list(item.get("evidence", [])),
    }

    if "price_raw" in item:
        snapshot["price_raw"] = item.get("price_raw", "")
    if "cycles" in item:
        snapshot["cycles"] = list(item.get("cycles", []))
    if "locations_raw" in item:
        snapshot["locations_raw"] = list(item.get("locations_raw", []))

    return snapshot


def _in_stock_from_parser(
    platform: str, html: str, final_url: str, fallback: int
) -> tuple[int, list[str], list[str], list[str], str]:
    """Parse HTML and return (in_stock_int, evidence, cycles, locations_raw, price_raw)."""
    if platform in ("WHMCS", "HostBill"):
        parser = parse_whmcs_page if platform == "WHMCS" else parse_hostbill_page
        parsed = parser(html, final_url)
        evidence = parsed.evidence
        if parsed.in_stock is True:
            return 1, evidence, parsed.cycles, parsed.locations_raw, parsed.price_raw
        if parsed.in_stock is False:
            return 0, evidence, parsed.cycles, parsed.locations_raw, parsed.price_raw
        return fallback, evidence, parsed.cycles, parsed.locations_raw, parsed.price_raw

    lowered = html.lower()
    if any(
        token in lowered
        for token in ("out of stock", "currently unavailable", "sold out", "缺貨中", "缺货中")
    ):
        return 0, ["generic-oos-marker"], [], [], ""
    return fallback, ["special-fallback"], [], [], ""


def check_stock(
    products: list[dict[str, Any]], http_client: HttpClient, max_workers: int = 12
) -> list[dict[str, Any]]:
    """Check live stock status for all products."""
    if not products:
        return []

    logger = get_logger("stock_checker")
    now = datetime.now(timezone.utc).isoformat()
    max_workers = coerce_positive_int(max_workers, default=12)
    rows: list[dict[str, Any]] = []

    def _check(item: dict[str, Any]) -> dict[str, Any]:
        product_url = item.get("canonical_url") or item.get("source_url")
        fallback_status = stock_value_from_record(item)

        response = http_client.get(str(product_url), force_english=True)
        if not response.ok:
            return {
                "product_id": item.get("product_id"),
                "canonical_url": product_url,
                "site": item.get("site", ""),
                "name_raw": item.get("name_raw", ""),
                "in_stock": fallback_status,
                "checked_at": now,
                "evidence": [f"fetch-error:{response.error}"],
            }

        in_stock, evidence, cycles, locs, price = _in_stock_from_parser(
            str(item.get("platform", "")), response.text, response.final_url, fallback_status
        )
        return {
            "product_id": item.get("product_id"),
            "canonical_url": product_url,
            "site": item.get("site", ""),
            "name_raw": item.get("name_raw", ""),
            "in_stock": in_stock,
            "checked_at": now,
            "cycles": cycles,
            "locations_raw": locs,
            "price_raw": price,
            "evidence": evidence + [f"tier:{response.tier}"],
        }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(_check, item): item for item in products}
        for future in as_completed(future_map):
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                item = future_map[future]
                logger.warning("stock check failed url=%s error=%s", item.get("canonical_url"), exc)
                rows.append(
                    {
                        "product_id": item.get("product_id"),
                        "canonical_url": item.get("canonical_url"),
                        "site": item.get("site", ""),
                        "name_raw": item.get("name_raw", ""),
                        "in_stock": -1,
                        "checked_at": now,
                        "evidence": [f"check-error:{exc}"],
                    }
                )

    logger.info("checked stock rows=%s", len(rows))
    return rows


def sync_stock_snapshot(
    products: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
    http_client: HttpClient,
    max_workers: int = 12,
    only_unknown: bool = True,
) -> StockSyncResult:
    """Refresh a product list against the latest stock snapshot with optional live checks."""
    now = datetime.now(timezone.utc).isoformat()
    updated_products = [dict(item) for item in products]
    product_rows = [
        item
        for item in updated_products
        if str(item.get("type", "product")).lower() != "category"
    ]

    previous_map = {_stock_key(item): item for item in previous_items if _stock_key(item)}
    targets = (
        [item for item in product_rows if stock_value_from_record(item) == -1]
        if only_unknown
        else list(product_rows)
    )

    checked_items_raw = check_stock(targets, http_client, max_workers=max_workers) if targets else []
    checked_map = {_stock_key(item): item for item in checked_items_raw if _stock_key(item)}
    ordered_checked_items = [
        checked_map[key]
        for key in (_stock_key(item) for item in targets)
        if key in checked_map
    ]

    product_by_url = {_stock_key(item): item for item in product_rows if _stock_key(item)}
    checked_urls = set()
    for checked in ordered_checked_items:
        url = _stock_key(checked)
        checked_urls.add(url)
        product = product_by_url.get(url)
        if not product:
            continue

        product["in_stock"] = stock_value_from_record(checked)
        product["evidence"] = list(checked.get("evidence", []))
        if "price_raw" in checked:
            product["price_raw"] = checked.get("price_raw", "")
        if "cycles" in checked:
            product["cycles"] = list(checked.get("cycles", []))
        if "locations_raw" in checked:
            product["locations_raw"] = list(checked.get("locations_raw", []))

    snapshot_items = [_snapshot_from_product(item) for item in product_rows]
    merged_snapshot = merge_with_previous(snapshot_items, previous_items)

    for item in merged_snapshot:
        url = _stock_key(item)
        if url in checked_urls:
            continue

        previous = previous_map.get(url)
        if previous and not item.get("changed") and previous.get("checked_at"):
            item["checked_at"] = previous["checked_at"]
        else:
            item["checked_at"] = now

    changed_items = [item for item in merged_snapshot if item.get("changed")]
    return StockSyncResult(
        products=updated_products,
        snapshot_items=merged_snapshot,
        checked_items=ordered_checked_items,
        changed_items=changed_items,
    )


def merge_with_previous(
    current_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge current stock check results with previous run, detecting restocks and changes."""
    previous_map = {_stock_key(item): item for item in previous_items if _stock_key(item)}
    merged: list[dict[str, Any]] = []
    for item in current_items:
        previous = previous_map.get(_stock_key(item))
        prev_stock = stock_value_from_record(previous) if previous else None
        curr_stock = stock_value_from_record(item)
        changed = prev_stock is not None and prev_stock != curr_stock
        restocked = prev_stock == 0 and curr_stock == 1
        destocked = prev_stock == 1 and curr_stock == 0
        merged.append(
            {
                **item,
                "previous_in_stock": prev_stock,
                "changed": changed,
                "restocked": restocked,
                "destocked": destocked,
            }
        )
    return merged


def load_stock(path: str = "data/stock.json") -> list[dict[str, Any]]:
    """Load stock check results from JSON file."""
    if not Path(path).exists():
        return []
    payload = load_json(path)
    return list(payload.get("items", []))


def write_stock(
    items: list[dict[str, Any]],
    run_id: str,
    checked_count: int = 0,
    path: str = "data/stock.json",
) -> None:
    """Write stock check results to JSON."""
    counts = count_stock_states(items)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stats": {
            "total_products": len(items),
            "checked_products": checked_count,
            "restocked": sum(1 for item in items if item.get("restocked")),
            "destocked": sum(1 for item in items if item.get("destocked")),
            "changed": sum(1 for item in items if item.get("changed")),
            "unknown": counts["unknown"],
        },
        "items": items,
    }
    dump_json(path, payload)
