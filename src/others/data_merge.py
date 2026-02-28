"""Handles deduplication and conflict-priority merging of products found via multiple crawl paths."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from src.misc.config_loader import dump_json, load_config, load_json
from src.misc.logger import get_logger
from src.misc.url_normalizer import canonicalize_for_merge, classify_url

try:
    _GLOBAL_CONFIG = load_config("config/config.json")
except Exception:  # noqa: BLE001
    _GLOBAL_CONFIG = {}
SCAN_TYPE_PRIORITY = _GLOBAL_CONFIG.get("data_merge", {}).get(
    "source_priority",
    {
        "discoverer": 1,
        "category_scanner": 2,
        "product_scanner": 3,
    },
)


def _scan_weight(scan_type: str) -> int:
    """Return numeric priority for a scan type (higher = more authoritative)."""
    return SCAN_TYPE_PRIORITY.get(scan_type, 0)


def _coerce_in_stock(record: dict[str, Any]) -> int:
    """Convert any stock representation to integer: 1=in_stock, 0=oos, -1=unknown."""
    # New-style integer field
    if "in_stock" in record:
        val = record["in_stock"]
        if isinstance(val, int) and val in {-1, 0, 1}:
            return val
    # Legacy string field
    legacy = str(record.get("stock_status", "")).strip().lower()
    if legacy == "in_stock":
        return 1
    if legacy == "out_of_stock":
        return 0
    return -1


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Clean, normalize, and validate a single incoming record."""
    canonical_url = unquote(
        canonicalize_for_merge(str(record.get("canonical_url") or record.get("source_url") or ""))
    )

    classification = classify_url(canonical_url)
    if classification.is_invalid_product_url:
        return None

    name_raw = str(record.get("name_raw", "")).strip()
    if "\n" in name_raw:
        name_raw = name_raw.splitlines()[0].strip()

    # Prefer scan_type; fall back to legacy source_priority
    scan_type = str(record.get("scan_type", record.get("source_priority", "product_scanner")))
    item_type = str(record.get("type", "product"))
    time_used = record.get("time_used", 0)

    sanitized: dict[str, Any] = {
        "site": str(record.get("site", "")),
        "platform": str(record.get("platform", "")),
        "canonical_url": canonical_url,
        "source_url": unquote(
            canonicalize_for_merge(str(record.get("source_url") or canonical_url))
        ),
        "scan_type": scan_type,
        "type": item_type,
        "time_used": time_used,
        "name_raw": name_raw,
        "description_raw": str(record.get("description_raw", "")),
        "in_stock": _coerce_in_stock(record),
        "evidence": list(record.get("evidence", [])),
        "first_seen_at": record.get("first_seen_at"),
        "last_seen_at": record.get("last_seen_at"),
    }

    # Include optional detail fields only when present
    if "price_raw" in record:
        sanitized["price_raw"] = str(record.get("price_raw", ""))
    if "cycles" in record:
        sanitized["cycles"] = list(record.get("cycles", []))
    if "locations_raw" in record:
        sanitized["locations_raw"] = list(record.get("locations_raw", []))

    return sanitized


def _content_dedup_key(record: dict[str, Any]) -> tuple[str, str, str] | None:
    """Build a key for same-content deduplication.

    Products with identical (name_raw, description_raw, site) are considered
    duplicates and merged.  Skip records with ``oos-marker`` evidence because
    OOS template pages share identical boilerplate text.
    """
    if "oos-marker" in record.get("evidence", []):
        return None
    name = str(record.get("name_raw", "")).strip()
    desc = str(record.get("description_raw", "")).strip()
    site = str(record.get("site", "")).strip()
    if not name or not site:
        return None
    return (site, name, desc)


def merge_records(
    discoverer_records: list[dict[str, Any]],
    product_records: list[dict[str, Any]],
    category_records: list[dict[str, Any]],
    previous_products: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge scanner outputs, deduplicate by URL and content, preserve timestamps."""
    logger = get_logger("data_merge")
    # Re-sanitize previous products to drop stale invalid URLs (e.g. cart.php?a=view)
    previous_by_url: dict[str, dict[str, Any]] = {}
    for old_item in previous_products or []:
        cleaned = _sanitize_record(old_item)
        if cleaned:
            previous_by_url[cleaned["canonical_url"]] = cleaned

    merged: dict[str, dict[str, Any]] = {}

    all_records: list[dict[str, Any]] = []
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
            weight_new = _scan_weight(sanitized["scan_type"])
            weight_old = _scan_weight(existing["scan_type"])
            if weight_new > weight_old:
                merged[url] = sanitized
            elif weight_new == weight_old and len(sanitized.get("evidence", [])) > len(
                existing.get("evidence", [])
            ):
                merged[url] = sanitized

    # --- Same-content deduplication ---
    content_seen: dict[tuple[str, str, str], str] = {}  # content_key → canonical_url
    urls_to_drop: set[str] = set()
    for url, record in sorted(merged.items(), key=lambda kv: -_scan_weight(kv[1]["scan_type"])):
        key = _content_dedup_key(record)
        if key is None:
            continue
        if key in content_seen:
            # Keep the one with higher scan weight (already sorted desc), drop this one
            winner_url = content_seen[key]
            winner = merged[winner_url]
            # Merge evidence from duplicate into winner
            combined_evidence = list(
                dict.fromkeys(winner.get("evidence", []) + record.get("evidence", []))
            )
            winner["evidence"] = combined_evidence
            if "content-dedup-merged" not in combined_evidence:
                winner["evidence"].append("content-dedup-merged")
            urls_to_drop.add(url)
        else:
            content_seen[key] = url
    for url in urls_to_drop:
        merged.pop(url, None)
    if urls_to_drop:
        logger.info("content-dedup removed %s duplicate records", len(urls_to_drop))

    # --- Timestamp bookkeeping ---
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
    """Return (added_urls, deleted_urls, stock_changed_urls)."""
    old_map = {item.get("canonical_url"): item for item in old_products}
    new_map = {item.get("canonical_url"): item for item in new_products}

    old_urls = set(old_map)
    new_urls = set(new_map)
    added = sorted(new_urls - old_urls)
    deleted = sorted(old_urls - new_urls)

    changed_stock: list[str] = []
    for url in sorted(old_urls & new_urls):
        if old_map[url].get("in_stock") != new_map[url].get("in_stock"):
            changed_stock.append(url)
    return added, deleted, changed_stock


def load_products(path: str = "data/products.json") -> list[dict[str, Any]]:
    """Load products from site-grouped JSON, returning a flat list with site/platform on each record."""
    if not Path(path).exists():
        return []
    payload = load_json(path)
    # New site-grouped format
    sites = payload.get("sites")
    if isinstance(sites, list):
        flat: list[dict[str, Any]] = []
        for site_block in sites:
            site_name = site_block.get("site", "")
            platform = site_block.get("platform", "")
            for item in site_block.get("products", []):
                flat.append({**item, "site": site_name, "platform": platform, "type": "product"})
            for item in site_block.get("categories", []):
                flat.append({**item, "site": site_name, "platform": platform, "type": "category"})
        return flat
    # Legacy flat format fallback
    return list(payload.get("products", []))


def _group_by_site(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a flat product list into site-grouped entries."""
    from collections import OrderedDict

    groups: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
    for item in products:
        key = (item.get("site", ""), item.get("platform", ""))
        if key not in groups:
            groups[key] = {"site": key[0], "platform": key[1], "categories": [], "products": []}
        # Strip site/platform from nested record to avoid duplication
        nested = {k: v for k, v in item.items() if k not in ("site", "platform")}
        if item.get("type") == "category":
            groups[key]["categories"].append(nested)
        else:
            groups[key]["products"].append(nested)

    sites: list[dict[str, Any]] = []
    for group in groups.values():
        group["product_count"] = len(group["products"])
        sites.append(group)
    return sites


def write_products(
    products: list[dict[str, Any]], run_id: str, path: str = "data/products.json"
) -> None:
    """Write product list to site-grouped JSON with computed stats."""
    in_stock_count = sum(1 for item in products if item.get("in_stock") == 1)
    oos_count = sum(1 for item in products if item.get("in_stock") == 0)
    sites = _group_by_site(products)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stats": {
            "total_sites": len(sites),
            "total_products": len(products),
            "in_stock": in_stock_count,
            "out_of_stock": oos_count,
            "unknown": len(products) - in_stock_count - oos_count,
        },
        "sites": sites,
    }
    dump_json(path, payload)
