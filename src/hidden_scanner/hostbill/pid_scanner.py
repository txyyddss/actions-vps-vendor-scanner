"""Scans HostBill instances for hidden products using incremental IDs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from src.hidden_scanner.scan_control import AdaptiveScanController
from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import canonicalize_for_merge, normalize_url
from src.others.state_store import StateStore
from src.parsers.common import in_stock_int
from src.parsers.hostbill_parser import parse_hostbill_page

_in_stock_int = in_stock_int


def scan_hostbill_pids(
    site: dict[str, Any],
    config: dict[str, Any],
    http_client: HttpClient,
    state_store: StateStore,
) -> list[dict[str, Any]]:
    """Executes scan_hostbill_pids logic."""
    logger = get_logger("hostbill_pid_scanner")
    site_name = site["name"]
    base_url = site["url"]
    now = datetime.now(timezone.utc).isoformat()
    site_state = state_store.get_site_state(site_name)

    scanner_cfg = config.get("scanner", {})
    defaults = scanner_cfg.get("default_scan_bounds", {})
    hard_max = int(
        site.get("scan_bounds", {}).get("hostbill_pid_max", defaults.get("hostbill_pid_max", 2500))
    )
    initial_floor = int(scanner_cfg.get("initial_scan_floor", 80))
    tail_window = int(scanner_cfg.get("stop_tail_window", 60))
    inactive_streak_limit = int(
        scanner_cfg.get(
            "stop_inactive_streak_product",
            scanner_cfg.get("stop_inactive_streak", max(40, tail_window)),
        )
    )
    learned_high = int(site_state.get("hostbill_pid_highwater", 0))
    resume_start = max(0, learned_high - tail_window) if learned_high > 0 else 0
    # Enforce one crawler worker per site; cross-site parallelism is handled by main_scanner.
    max_workers = 1
    batch_size = int(scanner_cfg.get("scan_batch_size", max_workers * 3))
    planner = AdaptiveScanController(
        hard_max=hard_max,
        initial_floor=initial_floor,
        tail_window=tail_window,
        learned_high=learned_high,
        inactive_streak_limit=inactive_streak_limit,
        start_id=resume_start,
    )
    records_by_url: dict[str, dict[str, Any]] = {}
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
                    "hostbill pid progress site=%s start=%s scanned_to=%s active_max=%s inactive_streak=%s discovered=%s",
                    site_name,
                    resume_start,
                    planner.last_processed_id,
                    planner.current_max,
                    planner.inactive_streak,
                    len(records_by_url),
                )

            future_map = {
                # Use FlareSolverr to handle challenge-protected sites.
                pool.submit(
                    http_client.get,
                    urljoin(base_url, f"index.php?/cart/&action=add&id={pid}"),
                    True,
                ): pid
                for pid in batch_ids
            }
            responses_by_id: dict[int, Any] = {}
            for future in as_completed(future_map):
                pid = future_map[future]
                try:
                    responses_by_id[pid] = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "hostbill pid fetch failed site=%s pid=%s error=%s", site_name, pid, exc
                    )

            for pid in batch_ids:
                response = responses_by_id.get(pid)
                discovered_new = False
                if response and response.ok:
                    parsed = parse_hostbill_page(response.text, response.final_url)

                    # Keep product-like pages even if currently out of stock.
                    if parsed.is_product or parsed.in_stock is False:
                        # Use requested_url (not final_url) because HostBill may
                        # redirect to session-dependent URLs.
                        canonical_url = canonicalize_for_merge(
                            normalize_url(response.requested_url, force_english=True)
                        )
                        record = {
                            "site": site_name,
                            "platform": "HostBill",
                            "scan_type": "product_scanner",
                            "pid": pid,
                            "canonical_url": canonical_url,
                            "source_url": response.requested_url,
                            "name_raw": parsed.name_raw,
                            "description_raw": parsed.description_raw,
                            "in_stock": _in_stock_int(parsed.in_stock),
                            "type": "product",
                            "time_used": response.elapsed_ms,
                            "price_raw": parsed.price_raw,
                            "cycles": parsed.cycles,
                            "locations_raw": parsed.locations_raw,
                            "evidence": parsed.evidence + [f"tier:{response.tier}"],
                            "first_seen_at": now,
                            "last_seen_at": now,
                        }
                        existing = records_by_url.get(canonical_url)
                        if existing is None:
                            records_by_url[canonical_url] = record
                            discovered_ids.append(pid)
                            discovered_new = True
                        elif len(record["evidence"]) > len(existing.get("evidence", [])):
                            records_by_url[canonical_url] = record

                if planner.mark(pid, discovered_new):
                    break

            if planner.should_stop:
                break

    if discovered_ids:
        state_store.update_site_state(
            site_name, {"hostbill_pid_highwater": max(max(discovered_ids), learned_high)}
        )

    logger.info(
        "hostbill pid scan site=%s discovered=%s unique=%s scanned_to=%s active_max=%s stop=%s",
        site_name,
        len(discovered_ids),
        len(records_by_url),
        planner.last_processed_id,
        planner.current_max,
        planner.stop_reason or "hard-max-or-exhausted",
    )
    return sorted(records_by_url.values(), key=lambda row: row["pid"])
