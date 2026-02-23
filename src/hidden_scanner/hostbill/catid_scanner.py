from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import normalize_url
from src.others.state_store import StateStore
from src.parsers.hostbill_parser import parse_hostbill_page


def scan_hostbill_catids(
    site: dict[str, Any],
    config: dict[str, Any],
    http_client: HttpClient,
    state_store: StateStore,
) -> list[dict[str, Any]]:
    logger = get_logger("hostbill_catid_scanner")
    site_name = site["name"]
    base_url = site["url"]
    site_state = state_store.get_site_state(site_name)

    scanner_cfg = config.get("scanner", {})
    defaults = scanner_cfg.get("default_scan_bounds", {})
    hard_max = int(site.get("scan_bounds", {}).get("hostbill_catid_max", defaults.get("hostbill_catid_max", 400)))
    initial_floor = int(scanner_cfg.get("initial_scan_floor", 80))
    tail_window = int(scanner_cfg.get("stop_tail_window", 60))
    learned_high = int(site_state.get("hostbill_catid_highwater", 0))
    scan_max = max(initial_floor, learned_high + tail_window)
    scan_max = min(scan_max, hard_max)

    cat_ids = list(range(0, scan_max + 1))
    max_workers = min(int(scanner_cfg.get("max_workers", 10)), 16)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    discovered_ids: list[int] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(http_client.get, urljoin(base_url, f"?cmd=cart&cat_id={cat_id}"), True, False): cat_id
            for cat_id in cat_ids
        }
        for future in as_completed(future_map):
            cat_id = future_map[future]
            response = future.result()
            if not response.ok:
                continue
            parsed = parse_hostbill_page(response.text, response.final_url)
            no_services = "no-services-yet" in parsed.evidence
            valid = (parsed.is_category or parsed.is_product) and not no_services
            if not valid:
                continue
            canonical = normalize_url(response.final_url, force_english=True)
            if canonical in seen_urls:
                continue
            seen_urls.add(canonical)
            discovered_ids.append(cat_id)
            records.append(
                {
                    "site": site_name,
                    "platform": "HostBill",
                    "scan_type": "category_scanner",
                    "source_priority": "category_scanner",
                    "cat_id": cat_id,
                    "canonical_url": canonical,
                    "source_url": response.requested_url,
                    "name_raw": parsed.name_raw,
                    "name_en": parsed.name_en,
                    "stock_status": "unknown",
                    "evidence": parsed.evidence,
                }
            )

    if discovered_ids:
        state_store.update_site_state(site_name, {"hostbill_catid_highwater": max(max(discovered_ids), learned_high)})

    logger.info(
        "hostbill catid scan site=%s max=%s discovered=%s unique=%s",
        site_name,
        scan_max,
        len(discovered_ids),
        len(records),
    )
    return sorted(records, key=lambda row: row["cat_id"])

