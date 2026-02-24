from __future__ import annotations
"""Validates live stock status for products against their latest webpage state."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.misc.config_loader import dump_json, load_json
from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.parsers.hostbill_parser import parse_hostbill_page
from src.parsers.whmcs_parser import parse_whmcs_page


def _status_from_parser(platform: str, html: str, final_url: str, fallback: str) -> tuple[str, list[str]]:
    """Executes _status_from_parser logic."""
    if platform == "WHMCS":
        parsed = parse_whmcs_page(html, final_url)
        evidence = parsed.evidence
        if parsed.in_stock is True:
            return "in_stock", evidence
        if parsed.in_stock is False:
            return "out_of_stock", evidence
        return fallback, evidence

    if platform == "HostBill":
        parsed = parse_hostbill_page(html, final_url)
        evidence = parsed.evidence
        if parsed.in_stock is True:
            return "in_stock", evidence
        if parsed.in_stock is False:
            return "out_of_stock", evidence
        return fallback, evidence

    lowered = html.lower()
    if any(token in lowered for token in ("out of stock", "currently unavailable", "sold out", "缺貨中", "缺货中")):
        return "out_of_stock", ["generic-oos-marker"]
    return fallback, ["special-fallback"]


def check_stock(products: list[dict[str, Any]], http_client: HttpClient, max_workers: int = 12) -> list[dict[str, Any]]:
    """Executes check_stock logic."""
    logger = get_logger("stock_checker")
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    def _check(item: dict[str, Any]) -> dict[str, Any]:
        """Executes _check logic."""
        product_url = item.get("canonical_url") or item.get("source_url")
        fallback_status = str(item.get("stock_status", "unknown"))
        response = http_client.get(str(product_url), force_english=True, allow_browser_fallback=True)
        if not response.ok:
            return {
                "product_id": item.get("product_id"),
                "canonical_url": product_url,
                "status": fallback_status,
                "checked_at": now,
                "evidence": [f"fetch-error:{response.error}"],
            }
        status, evidence = _status_from_parser(str(item.get("platform", "")), response.text, response.final_url, fallback_status)
        return {
            "product_id": item.get("product_id"),
            "canonical_url": product_url,
            "status": status,
            "checked_at": now,
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
                rows.append({
                    "product_id": item.get("product_id"),
                    "canonical_url": item.get("canonical_url"),
                    "status": str(item.get("stock_status", "unknown")),
                    "checked_at": now,
                    "evidence": [f"check-error:{exc}"],
                })

    logger.info("checked stock rows=%s", len(rows))
    return rows


def merge_with_previous(
    current_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Executes merge_with_previous logic."""
    previous_map = {item.get("canonical_url"): item for item in previous_items}
    merged: list[dict[str, Any]] = []
    for item in current_items:
        previous = previous_map.get(item.get("canonical_url"))
        previous_status = previous.get("status") if previous else None
        current_status = item.get("status")
        changed = previous_status is not None and previous_status != current_status
        restocked = previous_status == "out_of_stock" and current_status == "in_stock"
        merged.append(
            {
                **item,
                "previous_status": previous_status,
                "changed": changed,
                "restocked": restocked,
            }
        )
    return merged


def load_stock(path: str = "data/stock.json") -> list[dict[str, Any]]:
    """Executes load_stock logic."""
    if not Path(path).exists():
        return []
    payload = load_json(path)
    return list(payload.get("items", []))


def write_stock(items: list[dict[str, Any]], run_id: str, path: str = "data/stock.json") -> None:
    """Executes write_stock logic."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stats": {
            "total_checked": len(items),
            "restocked": sum(1 for item in items if item.get("restocked")),
        },
        "items": items,
    }
    dump_json(path, payload)

