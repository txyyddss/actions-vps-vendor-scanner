from __future__ import annotations
"""Handles deduplication and conflict-priority merging of products found via multiple crawl paths."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

from src.misc.config_loader import dump_json, load_config, load_json
from src.misc.logger import get_logger
from src.misc.url_normalizer import canonicalize_for_merge, classify_url

_GLOBAL_CONFIG = load_config("config/config.json")
SOURCE_PRIORITY = _GLOBAL_CONFIG.get("data_merge", {}).get("source_priority", {
    "discoverer": 1,
    "category_scanner": 2,
    "product_scanner": 3,
})


def _source_weight(source: str) -> int:
    """Executes _source_weight logic."""
    return SOURCE_PRIORITY.get(source, 0)


def _remove_language(url: str) -> str:
    parsed = urlparse(url)
    qs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in ("language", "lang", "locale")]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

def _sanitize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Executes _sanitize_record logic."""
    canonical_url = canonicalize_for_merge(str(record.get("canonical_url") or record.get("source_url") or ""))
    canonical_url = unquote(_remove_language(canonical_url))

    classification = classify_url(canonical_url)
    if classification.is_invalid_product_url:
        return None

    name_raw = str(record.get("name_raw", "")).strip()
    if "\n" in name_raw:
        name_raw = name_raw.splitlines()[0].strip()

    source = str(record.get("source_priority", "product_scanner"))
    
    # Process scan_type, type (product/category), and time_used if present
    scan_type = str(record.get("scan_type", source))
    item_type = str(record.get("type", "product"))
    time_used = record.get("time_used", 0)

    sanitized = {
        "site": str(record.get("site", "")),
        "platform": str(record.get("platform", "")),
        "canonical_url": canonical_url,
        "source_url": unquote(_remove_language(str(record.get("source_url") or canonical_url))),
        "source_priority": source,
        "scan_type": scan_type,
        "type": item_type,
        "time_used": time_used,
        "name_raw": name_raw,
        "description_raw": str(record.get("description_raw", "")),
        "evidence": list(record.get("evidence", [])),
        "first_seen_at": record.get("first_seen_at"),
        "last_seen_at": record.get("last_seen_at"),
    }
    
    # Include these fields only if they exist, to allow removing them from scanners
    if "stock_status" in record: sanitized["stock_status"] = str(record.get("stock_status", "unknown"))
    if "price_raw" in record: sanitized["price_raw"] = str(record.get("price_raw", ""))
    if "cycles" in record: sanitized["cycles"] = list(record.get("cycles", []))
    if "locations_raw" in record: sanitized["locations_raw"] = list(record.get("locations_raw", []))
    
    return sanitized


def merge_records(
    discoverer_records: list[dict[str, Any]],
    product_records: list[dict[str, Any]],
    category_records: list[dict[str, Any]],
    previous_products: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Executes merge_records logic."""
    logger = get_logger("data_merge")
    previous_by_url = {item.get("canonical_url"): item for item in (previous_products or [])}
    merged: dict[str, dict[str, Any]] = {}

    all_records = []
    all_records.extend(discoverer_records)
    all_records.extend(product_records)
    all_records.extend(category_records)
    for incoming in all_records:
        sanitized = _sanitize_record(incoming)
        if not sanitized:
            continue
        url = sanitized["canonical_url"]
        existing = merged.get(url)
        if existing is None:
            merged[url] = sanitized
        else:
            weight_new = _source_weight(sanitized["source_priority"])
            weight_old = _source_weight(existing["source_priority"])
            if weight_new > weight_old:
                merged[url] = sanitized
            elif weight_new == weight_old and len(sanitized.get("evidence", [])) > len(existing.get("evidence", [])):
                merged[url] = sanitized

    now = datetime.now(timezone.utc).isoformat()
    for url, record in merged.items():
        old = previous_by_url.get(url)
        if old and old.get("first_seen_at"):
            record["first_seen_at"] = old["first_seen_at"]
        elif not record.get("first_seen_at"):
            record["first_seen_at"] = now
        record["last_seen_at"] = now

    logger.info("merged records=%s", len(merged))
    return sorted(merged.values(), key=lambda item: item["canonical_url"])


def diff_products(
    old_products: list[dict[str, Any]],
    new_products: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """Executes diff_products logic."""
    old_map = {item.get("canonical_url"): item for item in old_products}
    new_map = {item.get("canonical_url"): item for item in new_products}

    old_urls = set(old_map)
    new_urls = set(new_map)
    added = sorted(new_urls - old_urls)
    deleted = sorted(old_urls - new_urls)

    changed_stock: list[str] = []
    for url in sorted(old_urls & new_urls):
        if old_map[url].get("stock_status") != new_map[url].get("stock_status"):
            changed_stock.append(url)
    return added, deleted, changed_stock


def load_products(path: str = "data/products.json") -> list[dict[str, Any]]:
    """Executes load_products logic."""
    if not Path(path).exists():
        return []
    payload = load_json(path)
    return list(payload.get("products", []))


def write_products(products: list[dict[str, Any]], run_id: str, path: str = "data/products.json") -> None:
    """Executes write_products logic."""
    in_stock = sum(1 for item in products if item.get("stock_status") == "in_stock")
    out_of_stock = sum(1 for item in products if item.get("stock_status") == "out_of_stock")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stats": {
            "total_products": len(products),
            "in_stock": in_stock,
            "out_of_stock": out_of_stock,
        },
        "products": products,
    }
    dump_json(path, payload)

