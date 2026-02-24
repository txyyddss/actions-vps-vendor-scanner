from __future__ import annotations
"""Periodic job to check stock statuses of all known products and send Telegram alerts for restocks."""

import json
from pathlib import Path

from src.misc.config_loader import load_config
from src.misc.http_client import HttpClient
from src.misc.logger import setup_logging
from src.misc.telegram_sender import TelegramSender
from src.others.stock_checker import check_stock, load_stock, merge_with_previous, write_stock


def main() -> None:
    """Executes main logic."""
    config = load_config("config/config.json")
    setup_logging(
        level=str(config.get("logging", {}).get("level", "INFO")),
        json_logs=bool(config.get("logging", {}).get("json_logs", False)),
    )

    products_path = Path("data/products.json")
    if not products_path.exists():
        write_stock(items=[], run_id="stock-run", path="data/stock.json")
        return

    products_payload = json.loads(products_path.read_text(encoding="utf-8-sig"))
    products = list(products_payload.get("products", []))
    if not products:
        run_id = products_payload.get("run_id") or "stock-run"
        tg = TelegramSender(config.get("telegram", {}))
        tg.send_run_stats(
            title="Stock Alert Run Summary",
            stats={
                "total_checked": 0,
                "restocked": 0,
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

    restocked_urls = [item["canonical_url"] for item in merged_items if item.get("restocked")]
    tg = TelegramSender(config.get("telegram", {}))
    if restocked_urls:
        tg.send_restock_alerts(restocked_urls)
    tg.send_run_stats(
        title="Stock Alert Run Summary",
        stats={
            "total_checked": len(merged_items),
            "restocked": len(restocked_urls),
            "changed": sum(1 for item in merged_items if item.get("changed")),
        },
    )

    run_id = products_payload.get("run_id") or "stock-run"
    write_stock(items=merged_items, run_id=run_id, path="data/stock.json")


if __name__ == "__main__":
    main()
