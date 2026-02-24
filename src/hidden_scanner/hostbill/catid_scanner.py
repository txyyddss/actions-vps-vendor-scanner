from __future__ import annotations
"""Scans HostBill instances for hidden categories using incremental IDs."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import normalize_url
from src.hidden_scanner.scan_control import AdaptiveScanController
from src.others.state_store import StateStore
from src.parsers.hostbill_parser import parse_hostbill_page


def scan_hostbill_catids(
    site: dict[str, Any],
    config: dict[str, Any],
    http_client: HttpClient,
    state_store: StateStore,
) -> list[dict[str, Any]]:
    """Executes scan_hostbill_catids logic."""
    logger = get_logger("hostbill_catid_scanner")
    site_name = site["name"]
    base_url = site["url"]
    site_state = state_store.get_site_state(site_name)

    scanner_cfg = config.get("scanner", {})
    defaults = scanner_cfg.get("default_scan_bounds", {})
    hard_max = int(site.get("scan_bounds", {}).get("hostbill_catid_max", defaults.get("hostbill_catid_max", 400)))
    initial_floor = int(scanner_cfg.get("initial_scan_floor", 80))
    tail_window = int(scanner_cfg.get("stop_tail_window", 60))
    inactive_streak_limit = int(
        scanner_cfg.get(
            "stop_inactive_streak_category",
            scanner_cfg.get("stop_inactive_streak", max(40, tail_window)),
        )
    )
    learned_high = int(site_state.get("hostbill_catid_highwater", 0))
    resume_start = max(0, learned_high - tail_window) if learned_high > 0 else 0
    max_workers = min(int(scanner_cfg.get("max_workers", 10)), 16)
    batch_size = int(scanner_cfg.get("scan_batch_size", max_workers * 3))
    planner = AdaptiveScanController(
        hard_max=hard_max,
        initial_floor=initial_floor,
        tail_window=tail_window,
        learned_high=learned_high,
        inactive_streak_limit=inactive_streak_limit,
        start_id=resume_start,
    )
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    discovered_ids: list[int] = []
    batches_processed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while True:
            batch_ids = planner.next_batch(batch_size)
            if not batch_ids:
                break
            batches_processed += 1
            if batches_processed == 1 or batches_processed % 10 == 0:
                logger.info(
                    "hostbill catid progress site=%s start=%s scanned_to=%s active_max=%s inactive_streak=%s discovered=%s",
                    site_name,
                    resume_start,
                    planner.last_processed_id,
                    planner.current_max,
                    planner.inactive_streak,
                    len(records),
                )

            future_map = {
                # Keep browser fallback enabled for category scans on challenge-protected sites.
                pool.submit(http_client.get, urljoin(base_url, f"?cmd=cart&cat_id={cat_id}"), True, True): cat_id
                for cat_id in batch_ids
            }
            responses_by_id: dict[int, Any] = {}
            for future in as_completed(future_map):
                cat_id = future_map[future]
                try:
                    responses_by_id[cat_id] = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("hostbill catid fetch failed site=%s cat_id=%s error=%s", site_name, cat_id, exc)

            for cat_id in batch_ids:
                response = responses_by_id.get(cat_id)
                discovered_new = False
                if response and response.ok:
                    parsed = parse_hostbill_page(response.text, response.final_url)
                    no_services = "no-services-yet" in parsed.evidence
                    valid = (parsed.is_category or parsed.is_product) and not no_services
                    if valid:
                        canonical = normalize_url(response.final_url, force_english=True)
                        if canonical not in seen_urls:
                            seen_urls.add(canonical)
                            discovered_ids.append(cat_id)
                            discovered_new = True
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

                if planner.mark(cat_id, discovered_new):
                    break

            if planner.should_stop:
                break

    if discovered_ids:
        state_store.update_site_state(site_name, {"hostbill_catid_highwater": max(max(discovered_ids), learned_high)})

    logger.info(
        "hostbill catid scan site=%s discovered=%s unique=%s scanned_to=%s active_max=%s stop=%s",
        site_name,
        len(discovered_ids),
        len(records),
        planner.last_processed_id,
        planner.current_max,
        planner.stop_reason or "hard-max-or-exhausted",
    )
    return sorted(records, key=lambda row: row["cat_id"])
