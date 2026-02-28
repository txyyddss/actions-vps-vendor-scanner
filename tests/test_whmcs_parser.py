from pathlib import Path

from src.parsers.whmcs_parser import parse_whmcs_page


def _fixture(name: str) -> str:
    return Path(f"tests/fixtures/{name}").read_text(encoding="utf-8")


def test_parse_whmcs_confproduct_in_stock() -> None:
    html = _fixture("whmcs_in_stock.html")
    parsed = parse_whmcs_page(html, "https://example.com/cart.php?a=confproduct&i=0")
    assert parsed.in_stock is True
    assert parsed.is_product is True
    assert "confproduct-final-url" in parsed.evidence
    assert "has-product-info" in parsed.evidence
    assert "Monthly" in parsed.cycles
    assert "Los Angeles" in parsed.locations_raw


def test_parse_whmcs_out_of_stock_marker() -> None:
    html = _fixture("whmcs_out_of_stock.html")
    parsed = parse_whmcs_page(html, "https://example.com/store/cat/outage-plan")
    assert parsed.in_stock is False
    assert parsed.is_product is True
    assert "oos-marker" in parsed.evidence


def test_parse_whmcs_store_category_not_product() -> None:
    html = _fixture("whmcs_in_stock.html")
    parsed = parse_whmcs_page(html, "https://example.com/store/cat-a")
    assert parsed.is_category is True
    assert parsed.is_product is False
    assert "has-product-info" not in parsed.evidence
    assert "oos-marker" not in parsed.evidence


def test_parse_whmcs_category_listing_ignores_oos_text() -> None:
    html = """
    <html><body>
      <h1>Shared VPS</h1>
      <div class="product-box">
        <h2>Plan A</h2>
        <div>$10.00 USD monthly</div>
        <div>0 available</div>
        <a href="/store/shared/plan-a">Order Now</a>
      </div>
    </body></html>
    """
    parsed = parse_whmcs_page(html, "https://example.com/store/shared")
    assert parsed.is_category is True
    assert parsed.is_product is False
    assert parsed.in_stock is None
    assert "oos-marker" not in parsed.evidence
    assert "has-product-info" not in parsed.evidence


def test_parse_whmcs_rp_store_product_is_product() -> None:
    html = _fixture("whmcs_out_of_stock.html")
    parsed = parse_whmcs_page(
        html,
        "https://example.com/index.php?language=english&rp=%2Fstore%2Fcat-a%2Foutage-plan",
    )
    assert parsed.is_product is True
