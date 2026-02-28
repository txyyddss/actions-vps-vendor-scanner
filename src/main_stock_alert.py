"""Periodic full stock sweep job that rechecks all products and sends stock change alerts."""

from __future__ import annotations

import json
from pathlib import Path

from src.misc.config_loader import coerce_positive_int, load_config
from src.misc.http_client import HttpClient
from src.misc.logger import setup_logging
from src.misc.stock_state import count_stock_states
from src.misc.telegram_sender import TelegramSender
from src.others.data_merge import load_products
from src.others.stock_checker import load_stock, sync_stock_snapshot, write_stock


def main() -> None:
    """Run a full stock sweep and send alerts."""
    config = load_config("config/config.json")
    setup_logging(
        level=str(config.get("logging", {}).get("level", "INFO")),
        json_logs=bool(config.get("logging", {}).get("json_logs", False)),
    )

    products_path = Path("data/products.json")
    if not products_path.exists():
        write_stock(items=[], run_id="stock-run", checked_count=0, path="data/stock.json")
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
                "total_products": 0,
                "checked_products": 0,
                "in_stock": 0,
                "out_of_stock": 0,
                "unknown": 0,
                "restocked": 0,
                "destocked": 0,
                "changed": 0,
            },
        )
        write_stock(items=[], run_id=run_id, checked_count=0, path="data/stock.json")
        return

    http_client = HttpClient(config=config)
    stock_sync = sync_stock_snapshot(
        products=products,
        previous_items=load_stock("data/stock.json"),
        http_client=http_client,
        max_workers=coerce_positive_int(config.get("scanner", {}).get("max_workers", 12), 12),
        only_unknown=False,
    )

    tg = TelegramSender(config.get("telegram", {}))

    if stock_sync.changed_items:
        tg.send_stock_change_alerts(stock_sync.changed_items)

    tg.send_run_stats(
        title="Stock Alert Run Summary",
        stats={
            **count_stock_states(stock_sync.snapshot_items),
            "total_products": len(stock_sync.snapshot_items),
            "checked_products": len(stock_sync.checked_items),
            "restocked": sum(1 for item in stock_sync.snapshot_items if item.get("restocked")),
            "destocked": sum(1 for item in stock_sync.snapshot_items if item.get("destocked")),
            "changed": len(stock_sync.changed_items),
        },
    )

    # Read run_id from the raw file
    raw = json.loads(products_path.read_text(encoding="utf-8-sig"))
    run_id = raw.get("run_id") or "stock-run"
    write_stock(
        items=stock_sync.snapshot_items,
        run_id=run_id,
        checked_count=len(stock_sync.checked_items),
        path="data/stock.json",
    )


if __name__ == "__main__":
    main()
