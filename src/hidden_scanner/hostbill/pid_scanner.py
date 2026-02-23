from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import canonicalize_for_merge, normalize_url
from src.others.state_store import StateStore
from src.parsers.hostbill_parser import parse_hostbill_page


def _status_from_flag(in_stock: bool | None) -> str:
    if in_stock is True:
        return "in_stock"
    if in_stock is False:
        return "out_of_stock"
    return "unknown"


def scan_hostbill_pids(
    site: dict[str, Any],
    config: dict[str, Any],
    http_client: HttpClient,
    state_store: StateStore,
) -> list[dict[str, Any]]:
    logger = get_logger("hostbill_pid_scanner")
    site_name = site["name"]
    base_url = site["url"]
    now = datetime.now(timezone.utc).isoformat()
    site_state = state_store.get_site_state(site_name)

    scanner_cfg = config.get("scanner", {})
    defaults = scanner_cfg.get("default_scan_bounds", {})
    hard_max = int(site.get("scan_bounds", {}).get("hostbill_pid_max", defaults.get("hostbill_pid_max", 2500)))
    initial_floor = int(scanner_cfg.get("initial_scan_floor", 80))
    tail_window = int(scanner_cfg.get("stop_tail_window", 60))
    learned_high = int(site_state.get("hostbill_pid_highwater", 0))
    scan_max = max(initial_floor, learned_high + tail_window)
    scan_max = min(scan_max, hard_max)

    ids = list(range(0, scan_max + 1))
    max_workers = min(int(scanner_cfg.get("max_workers", 10)), 16)
    records_by_url: dict[str, dict[str, Any]] = {}
    discovered_ids: list[int] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            # Keep browser fallback enabled for product scans on challenge-protected sites.
            pool.submit(http_client.get, urljoin(base_url, f"index.php?/cart/&action=add&id={pid}"), True, True): pid
            for pid in ids
        }
        for future in as_completed(future_map):
            pid = future_map[future]
            response = future.result()
            if not response.ok:
                continue
            parsed = parse_hostbill_page(response.text, response.final_url)

            # Keep product-like pages even if currently out of stock.
            if not (parsed.is_product or parsed.in_stock is False):
                continue

            canonical_url = canonicalize_for_merge(normalize_url(response.final_url, force_english=True))
            discovered_ids.append(pid)
            record = {
                "site": site_name,
                "platform": "HostBill",
                "scan_type": "product_scanner",
                "source_priority": "product_scanner",
                "pid": pid,
                "canonical_url": canonical_url,
                "source_url": response.requested_url,
                "stock_status": _status_from_flag(parsed.in_stock),
                "name_raw": parsed.name_raw,
                "name_en": parsed.name_en,
                "description_raw": parsed.description_raw,
                "description_en": parsed.description_en,
                "cycles": parsed.cycles,
                "locations_raw": parsed.locations_raw,
                "locations_en": parsed.locations_en,
                "price_raw": parsed.price_raw,
                "evidence": parsed.evidence + [f"tier:{response.tier}"],
                "first_seen_at": now,
                "last_seen_at": now,
            }
            existing = records_by_url.get(canonical_url)
            if existing is None or len(record["evidence"]) > len(existing.get("evidence", [])):
                records_by_url[canonical_url] = record

    if discovered_ids:
        state_store.update_site_state(site_name, {"hostbill_pid_highwater": max(max(discovered_ids), learned_high)})

    logger.info(
        "hostbill pid scan site=%s max=%s discovered=%s unique=%s",
        site_name,
        scan_max,
        len(discovered_ids),
        len(records_by_url),
    )
    return sorted(records_by_url.values(), key=lambda row: row["pid"])
