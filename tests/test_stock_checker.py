import src.others.stock_checker as stock_checker
from src.misc.http_client import FetchResult
from src.others.stock_checker import check_stock, merge_with_previous


class FakeHttpClient:
    def get(self, url: str, force_english: bool = True):  # noqa: ARG002
        if "oos" in url:
            html = '<div class="message message-danger">Out of Stock</div>'
            final_url = "https://example.com/store/cat/oos-plan"
        else:
            html = "<html><body><h2>Plan</h2></body></html>"
            final_url = "https://example.com/cart.php?a=confproduct&i=0"
        return FetchResult(
            ok=True,
            requested_url=url,
            final_url=final_url,
            status_code=200,
            text=html,
            headers={},
            tier="direct",
            elapsed_ms=1,
        )


def test_stock_checker_and_restock_merge() -> None:
    products = [
        {
            "product_id": "1",
            "canonical_url": "https://x/in",
            "platform": "WHMCS",
            "in_stock": -1,
            "site": "Test",
            "name_raw": "Plan",
        },
        {
            "product_id": "2",
            "canonical_url": "https://x/oos",
            "platform": "WHMCS",
            "in_stock": -1,
            "site": "Test",
            "name_raw": "Plan2",
        },
    ]
    rows = check_stock(products, FakeHttpClient(), max_workers=2)
    by_url = {row["canonical_url"]: row for row in rows}
    assert by_url["https://x/in"]["in_stock"] == 1
    assert by_url["https://x/oos"]["in_stock"] == 0

    previous = [
        {"canonical_url": "https://x/in", "in_stock": 0},
        {"canonical_url": "https://x/oos", "in_stock": 0},
    ]
    merged = merge_with_previous(rows, previous)
    merged_map = {row["canonical_url"]: row for row in merged}
    assert merged_map["https://x/in"]["restocked"] is True
    assert merged_map["https://x/oos"]["restocked"] is False


def test_destock_detection() -> None:
    current = [
        {"canonical_url": "https://x/a", "in_stock": 0},
    ]
    previous = [
        {"canonical_url": "https://x/a", "in_stock": 1},
    ]
    merged = merge_with_previous(current, previous)
    assert merged[0]["destocked"] is True
    assert merged[0]["restocked"] is False


def test_sync_stock_snapshot_checks_only_unknown_products_and_excludes_categories(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_check_stock(products, http_client, max_workers):  # noqa: ANN001, ARG001
        captured["checked_urls"] = [item["canonical_url"] for item in products]
        captured["max_workers"] = max_workers
        return [
            {
                "product_id": "1",
                "canonical_url": "https://x/unknown-a",
                "site": "Test",
                "name_raw": "Unknown A",
                "in_stock": 1,
                "checked_at": "checked-now-a",
                "price_raw": "$10",
                "cycles": ["monthly"],
                "locations_raw": ["US"],
                "evidence": ["live-a"],
            },
            {
                "product_id": "2",
                "canonical_url": "https://x/unknown-b",
                "site": "Test",
                "name_raw": "Unknown B",
                "in_stock": 0,
                "checked_at": "checked-now-b",
                "price_raw": "$20",
                "cycles": ["yearly"],
                "locations_raw": ["JP"],
                "evidence": ["live-b"],
            },
        ]

    monkeypatch.setattr(stock_checker, "check_stock", fake_check_stock)

    products = [
        {
            "product_id": "1",
            "canonical_url": "https://x/unknown-a",
            "platform": "WHMCS",
            "type": "product",
            "in_stock": -1,
            "site": "Test",
            "name_raw": "Unknown A",
        },
        {
            "product_id": "2",
            "canonical_url": "https://x/unknown-b",
            "platform": "WHMCS",
            "type": "product",
            "in_stock": -1,
            "site": "Test",
            "name_raw": "Unknown B",
        },
        {
            "product_id": "3",
            "canonical_url": "https://x/known",
            "platform": "WHMCS",
            "type": "product",
            "in_stock": 1,
            "site": "Test",
            "name_raw": "Known",
            "price_raw": "$30",
        },
        {
            "product_id": "4",
            "canonical_url": "https://x/category",
            "platform": "WHMCS",
            "type": "category",
            "in_stock": -1,
            "site": "Test",
            "name_raw": "Category",
        },
    ]
    previous = [
        {
            "canonical_url": "https://x/unknown-a",
            "in_stock": 0,
            "checked_at": "prev-a",
        },
        {
            "canonical_url": "https://x/known",
            "in_stock": 1,
            "checked_at": "prev-known",
        },
    ]

    result = stock_checker.sync_stock_snapshot(
        products=products,
        previous_items=previous,
        http_client=object(),
        max_workers=4,
        only_unknown=True,
    )

    assert captured["checked_urls"] == ["https://x/unknown-a", "https://x/unknown-b"]
    assert captured["max_workers"] == 4
    assert [item["canonical_url"] for item in result.checked_items] == [
        "https://x/unknown-a",
        "https://x/unknown-b",
    ]

    synced_by_url = {item["canonical_url"]: item for item in result.products}
    assert synced_by_url["https://x/unknown-a"]["in_stock"] == 1
    assert synced_by_url["https://x/unknown-a"]["price_raw"] == "$10"
    assert synced_by_url["https://x/unknown-b"]["in_stock"] == 0
    assert synced_by_url["https://x/known"]["in_stock"] == 1
    assert synced_by_url["https://x/category"]["in_stock"] == -1

    snapshot_by_url = {item["canonical_url"]: item for item in result.snapshot_items}
    assert set(snapshot_by_url) == {
        "https://x/unknown-a",
        "https://x/unknown-b",
        "https://x/known",
    }
    assert snapshot_by_url["https://x/unknown-a"]["restocked"] is True
    assert snapshot_by_url["https://x/unknown-a"]["changed"] is True
    assert snapshot_by_url["https://x/unknown-b"]["previous_in_stock"] is None
    assert snapshot_by_url["https://x/known"]["checked_at"] == "prev-known"

    assert [item["canonical_url"] for item in result.changed_items] == ["https://x/unknown-a"]


def test_sync_stock_snapshot_skips_live_check_when_no_unknown_products(monkeypatch) -> None:
    invoked = False

    def fake_check_stock(products, http_client, max_workers):  # noqa: ANN001, ARG001
        nonlocal invoked
        invoked = True
        return []

    monkeypatch.setattr(stock_checker, "check_stock", fake_check_stock)

    result = stock_checker.sync_stock_snapshot(
        products=[
            {
                "canonical_url": "https://x/known",
                "type": "product",
                "in_stock": 1,
                "site": "Test",
                "name_raw": "Known",
            },
            {
                "canonical_url": "https://x/category",
                "type": "category",
                "in_stock": -1,
                "site": "Test",
                "name_raw": "Category",
            },
        ],
        previous_items=[
            {
                "canonical_url": "https://x/known",
                "in_stock": 1,
                "checked_at": "prev-known",
            }
        ],
        http_client=object(),
        max_workers=3,
        only_unknown=True,
    )

    assert invoked is False
    assert result.checked_items == []
    assert len(result.snapshot_items) == 1
    assert result.snapshot_items[0]["canonical_url"] == "https://x/known"
    assert result.snapshot_items[0]["checked_at"] == "prev-known"
    assert result.changed_items == []


def test_sync_stock_snapshot_checks_all_products_when_full_sweep_requested(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_check_stock(products, http_client, max_workers):  # noqa: ANN001, ARG001
        captured["checked_urls"] = [item["canonical_url"] for item in products]
        captured["max_workers"] = max_workers
        return [
            {
                "canonical_url": "https://x/a",
                "site": "Test",
                "name_raw": "A",
                "in_stock": 1,
                "checked_at": "checked-a",
                "evidence": ["live-a"],
            },
            {
                "canonical_url": "https://x/b",
                "site": "Test",
                "name_raw": "B",
                "in_stock": 0,
                "checked_at": "checked-b",
                "evidence": ["live-b"],
            },
        ]

    monkeypatch.setattr(stock_checker, "check_stock", fake_check_stock)

    result = stock_checker.sync_stock_snapshot(
        products=[
            {
                "canonical_url": "https://x/a",
                "type": "product",
                "in_stock": 1,
                "site": "Test",
                "name_raw": "A",
            },
            {
                "canonical_url": "https://x/b",
                "type": "product",
                "in_stock": -1,
                "site": "Test",
                "name_raw": "B",
            },
            {
                "canonical_url": "https://x/category",
                "type": "category",
                "in_stock": -1,
                "site": "Test",
                "name_raw": "Category",
            },
        ],
        previous_items=[],
        http_client=object(),
        max_workers=5,
        only_unknown=False,
    )

    assert captured["checked_urls"] == ["https://x/a", "https://x/b"]
    assert captured["max_workers"] == 5
    assert [item["canonical_url"] for item in result.checked_items] == ["https://x/a", "https://x/b"]
    assert len(result.snapshot_items) == 2
    assert {item["canonical_url"] for item in result.snapshot_items} == {"https://x/a", "https://x/b"}


def test_write_stock_uses_new_stats_schema(tmp_path) -> None:
    import json

    path = tmp_path / "stock.json"
    stock_checker.write_stock(
        items=[
            {
                "canonical_url": "https://x/a",
                "in_stock": 1,
                "restocked": True,
                "destocked": False,
                "changed": True,
            },
            {
                "canonical_url": "https://x/b",
                "in_stock": -1,
                "restocked": False,
                "destocked": True,
                "changed": False,
            },
        ],
        run_id="run-1",
        checked_count=1,
        path=str(path),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["stats"] == {
        "total_products": 2,
        "checked_products": 1,
        "restocked": 1,
        "destocked": 1,
        "changed": 1,
        "unknown": 1,
    }
