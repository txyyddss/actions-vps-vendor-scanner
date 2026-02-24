from src.misc.http_client import FetchResult
from src.others.stock_checker import check_stock, merge_with_previous


class FakeHttpClient:
    def get(self, url: str, force_english: bool = True):  # noqa: ARG002
        if "oos" in url:
            html = '<div class="message message-danger">Out of Stock</div>'
            final_url = url
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
        {"product_id": "1", "canonical_url": "https://x/in", "platform": "WHMCS", "stock_status": "unknown"},
        {"product_id": "2", "canonical_url": "https://x/oos", "platform": "WHMCS", "stock_status": "unknown"},
    ]
    rows = check_stock(products, FakeHttpClient(), max_workers=2)
    by_url = {row["canonical_url"]: row for row in rows}
    assert by_url["https://x/in"]["status"] == "in_stock"
    assert by_url["https://x/oos"]["status"] == "out_of_stock"

    previous = [
        {"canonical_url": "https://x/in", "status": "out_of_stock"},
        {"canonical_url": "https://x/oos", "status": "out_of_stock"},
    ]
    merged = merge_with_previous(rows, previous)
    merged_map = {row["canonical_url"]: row for row in merged}
    assert merged_map["https://x/in"]["restocked"] is True
    assert merged_map["https://x/oos"]["restocked"] is False

