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
        {"product_id": "1", "canonical_url": "https://x/in", "platform": "WHMCS", "in_stock": -1, "site": "Test", "name_raw": "Plan"},
        {"product_id": "2", "canonical_url": "https://x/oos", "platform": "WHMCS", "in_stock": -1, "site": "Test", "name_raw": "Plan2"},
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
