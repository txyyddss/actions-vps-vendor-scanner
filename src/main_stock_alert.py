from __future__ import annotations
"""Periodic job to check stock statuses of all known products and send Telegram alerts for restocks."""

import json
from pathlib import Path

from src.misc.config_loader import load_config
from src.misc.http_client import HttpClient
from src.misc.logger import setup_logging
from src.misc.telegram_sender import TelegramSender
from src.others.data_merge import load_products
from src.others.stock_checker import check_stock, load_stock, merge_with_previous, write_stock


def main() -> None:
    """Run stock check and send alerts."""
    config = load_config("config/config.json")
    setup_logging(
        level=str(config.get("logging", {}).get("level", "INFO")),
        json_logs=bool(config.get("logging", {}).get("json_logs", False)),
    )

    products_path = Path("data/products.json")
    if not products_path.exists():
        write_stock(items=[], run_id="stock-run", path="data/stock.json")
        return

    products = load_products("data/products.json")
    if not products:
        # Read run_id from the raw file for stats reporting
        raw = json.loads(products_path.read_text(encoding="utf-8-sig"))
        run_id = raw.get("run_id") or "stock-run"
        tg = TelegramSender(config.get("telegram", {}))
        tg.send_run_stats(
            title="Stock Alert Run Summary",
            stats={
                "total_checked": 0,
                "restocked": 0,
                "destocked": 0,
                "changed": 0,
            },
        )
        write_stock(items=[], run_id=run_id, path="data/stock.json")
        return

    http_client = HttpClient(config=config)
    current_items = check_stock(
        products=products,
        http_client=http_client,
        max_workers=int(config.get("scanner", {}).get("max_workers", 12)),
    )
    previous_items = load_stock("data/stock.json")
    merged_items = merge_with_previous(current_items=current_items, previous_items=previous_items)

    tg = TelegramSender(config.get("telegram", {}))

    # Send restock alerts with full product info
    restocked_items = [item for item in merged_items if item.get("restocked")]
    if restocked_items:
        tg.send_restock_alerts(restocked_items)

    # Send comprehensive stock change alerts
    changed_items = [item for item in merged_items if item.get("changed")]
    if changed_items:
        tg.send_stock_change_alerts(changed_items)

    tg.send_run_stats(
        title="Stock Alert Run Summary",
        stats={
            "total_checked": len(merged_items),
            "in_stock": sum(1 for item in merged_items if item.get("in_stock") == 1),
            "out_of_stock": sum(1 for item in merged_items if item.get("in_stock") == 0),
            "restocked": len(restocked_items),
            "destocked": sum(1 for item in merged_items if item.get("destocked")),
            "changed": len(changed_items),
        },
    )

    # Read run_id from the raw file
    raw = json.loads(products_path.read_text(encoding="utf-8-sig"))
    run_id = raw.get("run_id") or "stock-run"
    write_stock(items=merged_items, run_id=run_id, path="data/stock.json")


if __name__ == "__main__":
    main()
