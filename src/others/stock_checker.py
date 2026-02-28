"""Validates live stock status for products against their latest webpage state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.misc.config_loader import dump_json, load_json
from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.parsers.hostbill_parser import parse_hostbill_page
from src.parsers.whmcs_parser import parse_whmcs_page


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
    logger = get_logger("stock_checker")
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    def _check(item: dict[str, Any]) -> dict[str, Any]:
        product_url = item.get("canonical_url") or item.get("source_url")
        # Convert legacy stock_status or use in_stock directly
        if "in_stock" in item:
            fallback_status = int(item["in_stock"])
        else:
            legacy = str(item.get("stock_status", "unknown")).lower()
            fallback_status = 1 if legacy == "in_stock" else (0 if legacy == "out_of_stock" else -1)

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


def merge_with_previous(
    current_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge current stock check results with previous run, detecting restocks and changes."""
    previous_map = {item.get("canonical_url"): item for item in previous_items}
    merged: list[dict[str, Any]] = []
    for item in current_items:
        previous = previous_map.get(item.get("canonical_url"))
        prev_stock = previous.get("in_stock") if previous else None
        curr_stock = item.get("in_stock")
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


def write_stock(items: list[dict[str, Any]], run_id: str, path: str = "data/stock.json") -> None:
    """Write stock check results to JSON."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stats": {
            "total_checked": len(items),
            "restocked": sum(1 for item in items if item.get("restocked")),
            "destocked": sum(1 for item in items if item.get("destocked")),
        },
        "items": items,
    }
    dump_json(path, payload)
