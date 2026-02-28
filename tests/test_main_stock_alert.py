import json

import src.main_stock_alert as main_stock_alert
from src.others.stock_checker import StockSyncResult


def test_main_stock_alert_uses_shared_full_sweep_sync(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "products.json").write_text(json.dumps({"run_id": "run-123"}), encoding="utf-8")

    sync_calls: dict[str, object] = {}
    sync_result = StockSyncResult(
        products=[
            {
                "canonical_url": "https://example.com/restock",
                "site": "Vendor A",
                "name_raw": "Restock Plan",
                "in_stock": 1,
            }
        ],
        snapshot_items=[
            {
                "canonical_url": "https://example.com/restock",
                "site": "Vendor A",
                "name_raw": "Restock Plan",
                "price_raw": "$10",
                "in_stock": 1,
                "restocked": True,
                "destocked": False,
                "changed": True,
            },
            {
                "canonical_url": "https://example.com/steady",
                "site": "Vendor B",
                "name_raw": "Steady Plan",
                "price_raw": "$20",
                "in_stock": 0,
                "restocked": False,
                "destocked": False,
                "changed": False,
            },
        ],
        checked_items=[
            {
                "canonical_url": "https://example.com/restock",
                "in_stock": 1,
            }
        ],
        changed_items=[
            {
                "canonical_url": "https://example.com/restock",
                "site": "Vendor A",
                "name_raw": "Restock Plan",
                "price_raw": "$10",
                "in_stock": 1,
                "restocked": True,
                "destocked": False,
                "changed": True,
            }
        ],
    )

    class DummyTelegramSender:
        instances: list["DummyTelegramSender"] = []

        def __init__(self, cfg) -> None:
            self.cfg = cfg
            self.stock_calls: list[list[dict[str, object]]] = []
            self.stats_calls: list[tuple[str, dict[str, int]]] = []
            DummyTelegramSender.instances.append(self)

        def send_stock_change_alerts(self, items):
            self.stock_calls.append(items)
            return True

        def send_run_stats(self, title, stats):
            self.stats_calls.append((title, stats))
            return True

    written: dict[str, object] = {}

    monkeypatch.setattr(
        main_stock_alert,
        "load_config",
        lambda path: {"logging": {"level": "INFO", "json_logs": False}, "scanner": {"max_workers": 0}},
    )
    monkeypatch.setattr(main_stock_alert, "setup_logging", lambda level, json_logs: None)
    monkeypatch.setattr(
        main_stock_alert,
        "load_products",
        lambda path: [{"canonical_url": "https://example.com/restock", "type": "product"}],
    )
    monkeypatch.setattr(main_stock_alert, "HttpClient", lambda **kwargs: object())
    monkeypatch.setattr(main_stock_alert, "load_stock", lambda path: [])

    def fake_sync_stock_snapshot(products, previous_items, http_client, max_workers, only_unknown):
        sync_calls["products"] = products
        sync_calls["previous_items"] = previous_items
        sync_calls["http_client"] = http_client
        sync_calls["max_workers"] = max_workers
        sync_calls["only_unknown"] = only_unknown
        return sync_result

    monkeypatch.setattr(main_stock_alert, "sync_stock_snapshot", fake_sync_stock_snapshot)
    monkeypatch.setattr(
        main_stock_alert,
        "write_stock",
        lambda items, run_id, checked_count, path: written.update(
            {
                "items": items,
                "run_id": run_id,
                "checked_count": checked_count,
                "path": path,
            }
        ),
    )
    monkeypatch.setattr(main_stock_alert, "TelegramSender", DummyTelegramSender)

    main_stock_alert.main()

    sender = DummyTelegramSender.instances[0]
    assert sync_calls["previous_items"] == []
    assert sync_calls["max_workers"] == 1
    assert sync_calls["only_unknown"] is False
    assert sender.stock_calls == [sync_result.changed_items]
    assert sender.stats_calls[0][1]["total_products"] == 2
    assert sender.stats_calls[0][1]["checked_products"] == 1
    assert sender.stats_calls[0][1]["restocked"] == 1
    assert sender.stats_calls[0][1]["destocked"] == 0
    assert sender.stats_calls[0][1]["changed"] == 1
    assert written["run_id"] == "run-123"
    assert written["checked_count"] == 1
    assert written["items"] == sync_result.snapshot_items


def test_main_stock_alert_still_writes_snapshot_when_nothing_changed(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "products.json").write_text(json.dumps({"run_id": "run-456"}), encoding="utf-8")

    sync_result = StockSyncResult(
        products=[
            {
                "canonical_url": "https://example.com/steady",
                "site": "Vendor A",
                "name_raw": "Steady Plan",
                "in_stock": 1,
            }
        ],
        snapshot_items=[
            {
                "canonical_url": "https://example.com/steady",
                "site": "Vendor A",
                "name_raw": "Steady Plan",
                "price_raw": "$10",
                "in_stock": 1,
                "restocked": False,
                "destocked": False,
                "changed": False,
            }
        ],
        checked_items=[
            {
                "canonical_url": "https://example.com/steady",
                "in_stock": 1,
            }
        ],
        changed_items=[],
    )

    class DummyTelegramSender:
        instances: list["DummyTelegramSender"] = []

        def __init__(self, cfg) -> None:
            self.cfg = cfg
            self.stock_calls: list[list[dict[str, object]]] = []
            self.stats_calls: list[tuple[str, dict[str, int]]] = []
            DummyTelegramSender.instances.append(self)

        def send_stock_change_alerts(self, items):
            self.stock_calls.append(items)
            return True

        def send_run_stats(self, title, stats):
            self.stats_calls.append((title, stats))
            return True

    written: dict[str, object] = {}

    monkeypatch.setattr(
        main_stock_alert,
        "load_config",
        lambda path: {"logging": {"level": "INFO", "json_logs": False}, "scanner": {}},
    )
    monkeypatch.setattr(main_stock_alert, "setup_logging", lambda level, json_logs: None)
    monkeypatch.setattr(
        main_stock_alert,
        "load_products",
        lambda path: [{"canonical_url": "https://example.com/steady", "type": "product"}],
    )
    monkeypatch.setattr(main_stock_alert, "HttpClient", lambda **kwargs: object())
    monkeypatch.setattr(main_stock_alert, "load_stock", lambda path: [])
    monkeypatch.setattr(main_stock_alert, "sync_stock_snapshot", lambda *args, **kwargs: sync_result)
    monkeypatch.setattr(
        main_stock_alert,
        "write_stock",
        lambda items, run_id, checked_count, path: written.update(
            {
                "items": items,
                "run_id": run_id,
                "checked_count": checked_count,
                "path": path,
            }
        ),
    )
    monkeypatch.setattr(main_stock_alert, "TelegramSender", DummyTelegramSender)

    main_stock_alert.main()

    sender = DummyTelegramSender.instances[0]
    assert sender.stock_calls == []
    assert sender.stats_calls[0][1]["checked_products"] == 1
    assert sender.stats_calls[0][1]["changed"] == 0
    assert written["run_id"] == "run-456"
    assert written["checked_count"] == 1
    assert written["items"] == sync_result.snapshot_items
