from __future__ import annotations

import src.main_scanner as main_scanner
from src.others.stock_checker import StockSyncResult


def test_merge_mode_runs_shared_stock_sync_and_writes_outputs(monkeypatch) -> None:
    discoverer_rows = [{"canonical_url": "https://example.com/discover"}]
    category_rows = [{"canonical_url": "https://example.com/category"}]
    product_rows = [{"canonical_url": "https://example.com/product"}]
    merged_before_sync = [
        {
            "site": "Vendor A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/product",
            "source_url": "https://example.com/product",
            "type": "product",
            "scan_type": "product_scanner",
            "name_raw": "Plan A",
            "description_raw": "",
            "in_stock": -1,
            "evidence": ["merged"],
        },
        {
            "site": "Vendor A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/category",
            "source_url": "https://example.com/category",
            "type": "category",
            "scan_type": "category_scanner",
            "name_raw": "Category",
            "description_raw": "",
            "in_stock": -1,
            "evidence": ["merged-category"],
        },
    ]
    synced_products = [
        {
            "site": "Vendor A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/product",
            "source_url": "https://example.com/product",
            "type": "product",
            "scan_type": "product_scanner",
            "name_raw": "Plan A",
            "description_raw": "",
            "in_stock": 1,
            "price_raw": "$10",
            "evidence": ["live"],
        },
        {
            "site": "Vendor A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/category",
            "source_url": "https://example.com/category",
            "type": "category",
            "scan_type": "category_scanner",
            "name_raw": "Category",
            "description_raw": "",
            "in_stock": -1,
            "evidence": ["merged-category"],
        },
    ]
    snapshot_items = [
        {
            "canonical_url": "https://example.com/product",
            "site": "Vendor A",
            "name_raw": "Plan A",
            "price_raw": "$10",
            "in_stock": 1,
            "changed": True,
            "restocked": True,
            "destocked": False,
        }
    ]
    sync_result = StockSyncResult(
        products=synced_products,
        snapshot_items=snapshot_items,
        checked_items=[{"canonical_url": "https://example.com/product", "in_stock": 1}],
        changed_items=snapshot_items,
    )

    old_products = [
        {
            "site": "Vendor Old",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/deleted",
            "type": "product",
            "scan_type": "product_scanner",
            "name_raw": "Removed",
            "in_stock": 0,
        }
    ]
    previous_stock = [
        {
            "canonical_url": "https://example.com/product",
            "in_stock": 0,
            "checked_at": "prev-check",
        }
    ]

    captured: dict[str, object] = {}
    writes: dict[str, object] = {}
    dashboard_calls: dict[str, object] = {}

    class DummyTelegramSender:
        instances: list["DummyTelegramSender"] = []

        def __init__(self, cfg) -> None:
            self.cfg = cfg
            self.product_calls: list[dict[str, object]] = []
            self.stock_calls: list[list[dict[str, object]]] = []
            self.stats_calls: list[tuple[str, dict[str, object]]] = []
            DummyTelegramSender.instances.append(self)

        def send_product_changes(
            self, new_urls, deleted_urls, current_products=None, previous_products=None
        ):
            self.product_calls.append(
                {
                    "new_urls": new_urls,
                    "deleted_urls": deleted_urls,
                    "current_products": current_products,
                    "previous_products": previous_products,
                }
            )
            return True

        def send_stock_change_alerts(self, items):
            self.stock_calls.append(items)
            return True

        def send_run_stats(self, title, stats):
            self.stats_calls.append((title, stats))
            return True

    monkeypatch.setattr(
        main_scanner,
        "_load_tmp",
        lambda name: {
            "discoverer": discoverer_rows,
            "category": category_rows,
            "product": product_rows,
        }[name],
    )
    monkeypatch.setattr(main_scanner, "load_products", lambda path: old_products)
    monkeypatch.setattr(main_scanner, "merge_records", lambda *args, **kwargs: merged_before_sync)
    monkeypatch.setattr(main_scanner, "_attach_product_ids", lambda products: products)
    monkeypatch.setattr(main_scanner, "load_stock", lambda path: previous_stock)

    def fake_sync_stock_snapshot(products, previous_items, http_client, max_workers, only_unknown):
        captured["sync_products"] = products
        captured["sync_previous_items"] = previous_items
        captured["sync_http_client"] = http_client
        captured["sync_max_workers"] = max_workers
        captured["sync_only_unknown"] = only_unknown
        return sync_result

    def fake_diff_products(old, new):
        captured["diff_old"] = old
        captured["diff_new"] = new
        return (
            ["https://example.com/product"],
            ["https://example.com/deleted"],
            ["https://example.com/product"],
        )

    monkeypatch.setattr(main_scanner, "sync_stock_snapshot", fake_sync_stock_snapshot)
    monkeypatch.setattr(main_scanner, "diff_products", fake_diff_products)
    monkeypatch.setattr(main_scanner, "TelegramSender", DummyTelegramSender)
    monkeypatch.setattr(
        main_scanner,
        "write_products",
        lambda products, run_id, path: writes.update(
            {"products": products, "products_run_id": run_id, "products_path": path}
        ),
    )
    monkeypatch.setattr(
        main_scanner,
        "write_stock",
        lambda items, run_id, checked_count, path: writes.update(
            {
                "stock_items": items,
                "stock_run_id": run_id,
                "stock_checked_count": checked_count,
                "stock_path": path,
            }
        ),
    )
    monkeypatch.setattr(
        main_scanner,
        "generate_dashboard",
        lambda payload, output_dir, dashboard_cfg: dashboard_calls.update(
            {
                "payload": payload,
                "output_dir": output_dir,
                "dashboard_cfg": dashboard_cfg,
            }
        ),
    )
    monkeypatch.setattr(main_scanner, "_now_run_id", lambda: "run-merge")

    result = main_scanner._merge_mode(
        config={"scanner": {"max_workers": 7}, "telegram": {}, "dashboard": {"title": "Test"}},
        http_client=object(),
    )

    sender = DummyTelegramSender.instances[0]
    assert result == synced_products
    assert captured["sync_products"] == merged_before_sync
    assert captured["sync_previous_items"] == previous_stock
    assert captured["sync_max_workers"] == 7
    assert captured["sync_only_unknown"] is True
    assert captured["diff_old"] == old_products
    assert captured["diff_new"] == synced_products

    assert sender.product_calls[0]["new_urls"] == ["https://example.com/product"]
    assert sender.product_calls[0]["deleted_urls"] == ["https://example.com/deleted"]
    assert sender.product_calls[0]["current_products"] == synced_products
    assert sender.product_calls[0]["previous_products"] == old_products
    assert sender.stock_calls == [snapshot_items]
    assert sender.stats_calls[0][1]["stock_changed"] == 1
    assert sender.stats_calls[0][1]["checked_products"] == 1
    assert sender.stats_calls[0][1]["unknown_remaining"] == 0

    assert writes["products"] == synced_products
    assert writes["products_run_id"] == "run-merge"
    assert writes["products_path"] == "data/products.json"
    assert writes["stock_items"] == snapshot_items
    assert writes["stock_run_id"] == "run-merge"
    assert writes["stock_checked_count"] == 1
    assert writes["stock_path"] == "data/stock.json"

    assert dashboard_calls["output_dir"] == "web"
    assert dashboard_calls["dashboard_cfg"] == {"title": "Test"}
    assert dashboard_calls["payload"]["stats"]["in_stock"] == 1
    assert dashboard_calls["payload"]["stats"]["unknown"] == 1
