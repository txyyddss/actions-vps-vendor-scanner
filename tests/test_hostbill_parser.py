from pathlib import Path

from src.parsers.hostbill_parser import parse_hostbill_page


def _fixture(name: str) -> str:
    return Path(f"tests/fixtures/{name}").read_text(encoding="utf-8")


def test_parse_hostbill_in_stock_step() -> None:
    html = _fixture("hostbill_in_stock.html")
    parsed = parse_hostbill_page(html, "https://clients.example.com/index.php?/cart/&step=3")
    assert parsed.in_stock is True
    assert parsed.is_product is True
    assert "Annually" in parsed.cycles


def test_parse_hostbill_out_of_stock_js_marker() -> None:
    html = _fixture("hostbill_out_of_stock.html")
    parsed = parse_hostbill_page(html, "https://clients.example.com/index.php?/cart/&action=add&id=94")
    assert parsed.in_stock is False
    assert "js-errors-array" in parsed.evidence
    assert "disabled-oos-button" in parsed.evidence

