"""Main orchestration script for discovering links and scanning products across all configured vendors."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.discoverer.link_discoverer import LinkDiscoverer
from src.hidden_scanner.hostbill.catid_scanner import scan_hostbill_catids
from src.hidden_scanner.hostbill.pid_scanner import scan_hostbill_pids
from src.hidden_scanner.whmcs.gid_scanner import scan_whmcs_gids
from src.hidden_scanner.whmcs.pid_scanner import scan_whmcs_pids
from src.misc.config_loader import load_config, load_sites
from src.misc.dashboard_generator import generate_dashboard
from src.misc.http_client import HttpClient
from src.misc.logger import get_logger, setup_logging
from src.misc.telegram_sender import TelegramSender
from src.others.data_merge import diff_products, load_products, merge_records, write_products
from src.others.state_store import StateStore
from src.others.stock_checker import load_stock, sync_stock_snapshot, write_stock
from src.site_specific.acck_api import scan_acck_api
from src.site_specific.akile_api import scan_akile_api

TMP_DIR = Path("data/tmp")


def _now_run_id() -> str:
    """Executes _now_run_id logic."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_tmp(name: str) -> list[dict[str, Any]]:
    """Executes _load_tmp logic."""
    path = TMP_DIR / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_tmp(name: str, payload: list[dict[str, Any]]) -> None:
    """Executes _save_tmp logic."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _discover_mode(
    sites: list[dict[str, Any]], config: dict[str, Any], http_client: HttpClient
) -> list[dict[str, Any]]:
    """Executes _discover_mode logic."""
    scanner_cfg = config.get("scanner", {})
    logger = get_logger("main_scanner")
    discover_site_workers = max(
        1, int(scanner_cfg.get("discoverer_max_workers", scanner_cfg.get("max_workers", 12)))
    )
    site_discoverer = LinkDiscoverer(
        http_client=http_client,
        max_depth=int(scanner_cfg.get("discoverer_max_depth", 3)),
        max_pages=int(scanner_cfg.get("discoverer_max_pages", 500)),
        # Discover each site with a single crawl worker to reduce contention/challenge noise.
        max_workers=1,
    )

    records: list[dict[str, Any]] = []
    targets = [site for site in sites if site.get("enabled") and site.get("discoverer")]
    if targets:
        with ThreadPoolExecutor(max_workers=min(discover_site_workers, len(targets))) as pool:
            future_map = {
                pool.submit(
                    site_discoverer.discover, site_name=site["name"], base_url=site["url"]
                ): site
                for site in targets
            }
            for future in as_completed(future_map):
                site = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("discoverer failed site=%s error=%s", site.get("name", ""), exc)
                    continue
                for url in result.product_candidates:
                    records.append(
                        {
                            "site": site["name"],
                            "platform": site.get("category", ""),
                            "scan_type": "discoverer",
                            "canonical_url": url,
                            "source_url": url,
                            "type": "product",
                            "time_used": 0,
                            "name_raw": "",
                            "description_raw": "",
                            "in_stock": -1,
                            "evidence": ["discoverer-candidate"],
                        }
                    )
                for url in result.category_candidates:
                    records.append(
                        {
                            "site": site["name"],
                            "platform": site.get("category", ""),
                            "scan_type": "discoverer",
                            "canonical_url": url,
                            "source_url": url,
                            "type": "category",
                            "time_used": 0,
                            "name_raw": "",
                            "description_raw": "",
                            "in_stock": -1,
                            "evidence": ["discoverer-category-candidate"],
                        }
                    )
    _save_tmp("discoverer", records)
    return records


def _category_mode(
    sites: list[dict[str, Any]],
    config: dict[str, Any],
    http_client: HttpClient,
    state_store: StateStore,
) -> list[dict[str, Any]]:
    """Executes _category_mode logic."""
    scanner_cfg = config.get("scanner", {})
    targets = [site for site in sites if site.get("enabled") and site.get("category_scanner")]
    rows: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(8, int(scanner_cfg.get("max_workers", 12)))) as pool:
        future_map = {}
        for site in targets:
            category = str(site.get("category", "")).lower()
            if category == "whmcs":
                future_map[pool.submit(scan_whmcs_gids, site, config, http_client, state_store)] = (
                    site["name"]
                )
            elif category == "hostbill":
                future_map[
                    pool.submit(scan_hostbill_catids, site, config, http_client, state_store)
                ] = site["name"]
        for future in as_completed(future_map):
            try:
                rows.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                logger = get_logger("main_scanner")
                logger.warning(
                    "category scan failed site=%s error=%s", future_map.get(future, "unknown"), exc
                )

    _save_tmp("category", rows)
    return rows


def _product_mode(
    sites: list[dict[str, Any]],
    config: dict[str, Any],
    http_client: HttpClient,
    state_store: StateStore,
) -> list[dict[str, Any]]:
    """Executes _product_mode logic."""
    scanner_cfg = config.get("scanner", {})
    targets = [site for site in sites if site.get("enabled")]
    rows: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(8, int(scanner_cfg.get("max_workers", 12)))) as pool:
        future_map = {}
        for site in targets:
            special_crawler = str(site.get("special_crawler", "")).strip().lower()
            category = str(site.get("category", "")).lower()
            # Special crawlers always run; product_scanner flag only gates WHMCS/HostBill PID scans.
            if special_crawler == "acck_api":
                future_map[pool.submit(scan_acck_api, site, http_client)] = site["name"]
            elif special_crawler == "akile_api":
                future_map[pool.submit(scan_akile_api, site, http_client)] = site["name"]
            elif not site.get("product_scanner"):
                continue
            elif category == "whmcs":
                future_map[pool.submit(scan_whmcs_pids, site, config, http_client, state_store)] = (
                    site["name"]
                )
            elif category == "hostbill":
                future_map[
                    pool.submit(scan_hostbill_pids, site, config, http_client, state_store)
                ] = site["name"]

        for future in as_completed(future_map):
            try:
                rows.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                logger = get_logger("main_scanner")
                logger.warning(
                    "product scan failed site=%s error=%s", future_map.get(future, "unknown"), exc
                )

    _save_tmp("product", rows)
    return rows


def _attach_product_ids(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Executes _attach_product_ids logic."""
    for item in products:
        key = item.get("canonical_url", "")
        item["product_id"] = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return products


def _merge_mode(config: dict[str, Any], http_client: HttpClient) -> list[dict[str, Any]]:
    """Executes _merge_mode logic."""
    discoverer_rows = _load_tmp("discoverer")
    category_rows = _load_tmp("category")
    product_rows = _load_tmp("product")

    old_products = load_products("data/products.json")
    merged = merge_records(
        discoverer_rows, product_rows, category_rows, previous_products=old_products
    )
    merged = _attach_product_ids(merged)
    stock_sync = sync_stock_snapshot(
        products=merged,
        previous_items=load_stock("data/stock.json"),
        http_client=http_client,
        max_workers=int(config.get("scanner", {}).get("max_workers", 12)),
        only_unknown=True,
    )
    merged = stock_sync.products

    added, deleted, changed_stock = diff_products(old_products, merged)
    run_id = _now_run_id()

    tg = TelegramSender(config.get("telegram", {}))
    if added or deleted:
        tg.send_product_changes(
            new_urls=added,
            deleted_urls=deleted,
            current_products=merged,
            previous_products=old_products,
        )
    if stock_sync.changed_items:
        tg.send_stock_change_alerts(stock_sync.changed_items)
    tg.send_run_stats(
        title="Scanner Run Summary",
        stats={
            "run_id": run_id,
            "merged_products": len(merged),
            "new_products": len(added),
            "deleted_products": len(deleted),
            "stock_changed": len(changed_stock),
            "checked_products": len(stock_sync.checked_items),
            "unknown_remaining": sum(
                1 for item in stock_sync.snapshot_items if item.get("in_stock") == -1
            ),
        },
    )

    write_products(merged, run_id=run_id, path="data/products.json")
    write_stock(
        items=stock_sync.snapshot_items,
        run_id=run_id,
        checked_count=len(stock_sync.checked_items),
        path="data/stock.json",
    )
    # Build dashboard data from the site-grouped structure
    from src.others.data_merge import _group_by_site

    sites = _group_by_site(merged)
    products_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_sites": len(sites),
            "total_products": len(merged),
            "in_stock": sum(1 for item in merged if item.get("in_stock") == 1),
            "out_of_stock": sum(1 for item in merged if item.get("in_stock") == 0),
            "unknown": sum(1 for item in merged if item.get("in_stock") == -1),
        },
        "sites": sites,
    }
    generate_dashboard(
        products_payload, output_dir="web", dashboard_cfg=config.get("dashboard", {})
    )
    return merged


def main() -> None:
    """Executes main logic."""
    parser = argparse.ArgumentParser(description="VPS scanner orchestrator")
    parser.add_argument(
        "--mode", required=True, choices=["discoverer", "category", "product", "merge", "all"]
    )
    parser.add_argument("--site", default="", help="optional site name filter")
    args = parser.parse_args()

    config = load_config("config/config.json")
    setup_logging(
        level=str(config.get("logging", {}).get("level", "INFO")),
        json_logs=bool(config.get("logging", {}).get("json_logs", False)),
    )
    sites = load_sites("config/sites.json")
    if args.site:
        sites = [site for site in sites if site.get("name", "").lower() == args.site.lower()]
    http_client = HttpClient(config=config)
    state_store = StateStore(Path("data/state.json"))

    if args.mode == "discoverer":
        _discover_mode(sites, config, http_client)
    elif args.mode == "category":
        _category_mode(sites, config, http_client, state_store)
    elif args.mode == "product":
        _product_mode(sites, config, http_client, state_store)
    elif args.mode == "merge":
        _merge_mode(config, http_client)
    else:
        _discover_mode(sites, config, http_client)
        _category_mode(sites, config, http_client, state_store)
        _product_mode(sites, config, http_client, state_store)
        _merge_mode(config, http_client)


if __name__ == "__main__":
    main()
