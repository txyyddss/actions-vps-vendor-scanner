from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import normalize_url
from src.others.state_store import StateStore
from src.parsers.whmcs_parser import parse_whmcs_page


def scan_whmcs_gids(
    site: dict[str, Any],
    config: dict[str, Any],
    http_client: HttpClient,
    state_store: StateStore,
) -> list[dict[str, Any]]:
    logger = get_logger("whmcs_gid_scanner")
    site_name = site["name"]
    base_url = site["url"]
    site_state = state_store.get_site_state(site_name)

    scanner_cfg = config.get("scanner", {})
    defaults = scanner_cfg.get("default_scan_bounds", {})
    hard_max = int(site.get("scan_bounds", {}).get("whmcs_gid_max", defaults.get("whmcs_gid_max", 600)))
    initial_floor = int(scanner_cfg.get("initial_scan_floor", 80))
    tail_window = int(scanner_cfg.get("stop_tail_window", 60))
    learned_high = int(site_state.get("whmcs_gid_highwater", 0))
    scan_max = max(initial_floor, learned_high + tail_window)
    scan_max = min(scan_max, hard_max)

    gids = list(range(0, scan_max + 1))
    max_workers = min(int(scanner_cfg.get("max_workers", 10)), 12)
    results: list[dict[str, Any]] = []
    unique_urls: set[str] = set()
    discovered_ids: list[int] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            # Keep browser fallback enabled for category scans on challenge-protected sites.
            pool.submit(http_client.get, urljoin(base_url, f"cart.php?gid={gid}"), True, True): gid for gid in gids
        }
        for future in as_completed(future_map):
            gid = future_map[future]
            response = future.result()
            if not response.ok:
                continue
            parsed = parse_whmcs_page(response.text, response.final_url)
            if not parsed.is_category:
                continue
            category_url = normalize_url(response.final_url, force_english=True)
            if category_url in unique_urls:
                continue
            unique_urls.add(category_url)
            discovered_ids.append(gid)
            results.append(
                {
                    "site": site_name,
                    "platform": "WHMCS",
                    "scan_type": "category_scanner",
                    "source_priority": "category_scanner",
                    "gid": gid,
                    "canonical_url": category_url,
                    "source_url": response.requested_url,
                    "name_raw": parsed.name_raw,
                    "name_en": parsed.name_en,
                    "stock_status": "unknown",
                    "evidence": parsed.evidence,
                }
            )

    if discovered_ids:
        new_high = max(discovered_ids)
        state_store.update_site_state(site_name, {"whmcs_gid_highwater": max(new_high, learned_high)})

    logger.info(
        "whmcs gid scan site=%s max=%s discovered=%s unique=%s",
        site_name,
        scan_max,
        len(discovered_ids),
        len(results),
    )
    return sorted(results, key=lambda row: row["gid"])
