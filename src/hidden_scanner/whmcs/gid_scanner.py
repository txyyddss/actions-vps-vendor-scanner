from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import normalize_url
from src.hidden_scanner.scan_control import AdaptiveScanController
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
    inactive_streak_limit = int(scanner_cfg.get("stop_inactive_streak", max(40, tail_window)))
    learned_high = int(site_state.get("whmcs_gid_highwater", 0))
    max_workers = min(int(scanner_cfg.get("max_workers", 10)), 12)
    batch_size = int(scanner_cfg.get("scan_batch_size", max_workers * 3))
    planner = AdaptiveScanController(
        hard_max=hard_max,
        initial_floor=initial_floor,
        tail_window=tail_window,
        learned_high=learned_high,
        inactive_streak_limit=inactive_streak_limit,
    )
    results: list[dict[str, Any]] = []
    unique_urls: set[str] = set()
    discovered_ids: list[int] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while True:
            batch_ids = planner.next_batch(batch_size)
            if not batch_ids:
                break

            future_map = {
                # Keep browser fallback enabled for category scans on challenge-protected sites.
                pool.submit(http_client.get, urljoin(base_url, f"cart.php?gid={gid}"), True, True): gid
                for gid in batch_ids
            }
            responses_by_id: dict[int, Any] = {}
            for future in as_completed(future_map):
                gid = future_map[future]
                try:
                    responses_by_id[gid] = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("whmcs gid fetch failed site=%s gid=%s error=%s", site_name, gid, exc)

            for gid in batch_ids:
                response = responses_by_id.get(gid)
                discovered_new = False

                if response and response.ok:
                    parsed = parse_whmcs_page(response.text, response.final_url)
                    if parsed.is_category:
                        category_url = normalize_url(response.final_url, force_english=True)
                        if category_url not in unique_urls:
                            unique_urls.add(category_url)
                            discovered_ids.append(gid)
                            discovered_new = True
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

                if planner.mark(gid, discovered_new):
                    break

            if planner.should_stop:
                break

    if discovered_ids:
        new_high = max(discovered_ids)
        state_store.update_site_state(site_name, {"whmcs_gid_highwater": max(new_high, learned_high)})

    logger.info(
        "whmcs gid scan site=%s discovered=%s unique=%s scanned_to=%s active_max=%s stop=%s",
        site_name,
        len(discovered_ids),
        len(results),
        planner.last_processed_id,
        planner.current_max,
        planner.stop_reason or "hard-max-or-exhausted",
    )
    return sorted(results, key=lambda row: row["gid"])
