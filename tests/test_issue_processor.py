from pathlib import Path

from src.main_issue_processor import (
    _apply_site_change,
    _build_site_entry,
    _parse_markdown_form,
    _parse_positive_int,
    _validate_site_payload,
)


def test_parse_markdown_form() -> None:
    body = """### Action
add
### Site Name
Example
### Base URL
https://example.com/
### Expected Product Number
15
"""
    fields = _parse_markdown_form(body)
    assert fields["action"] == "add"
    assert fields["site_name"] == "Example"
    assert fields["base_url"] == "https://example.com/"
    assert fields["expected_product_number"] == "15"


def test_parse_positive_int() -> None:
    assert _parse_positive_int("20") == 20
    assert _parse_positive_int(">= 33 products") == 33
    assert _parse_positive_int("0") is None
    assert _parse_positive_int("abc") is None


def test_validate_site_payload_requires_expected_number_for_add() -> None:
    ok, reason = _validate_site_payload(
        {
            "action": "add",
            "site_name": "Example",
            "base_url": "https://example.com/",
            "platform": "WHMCS",
            "expected_product_number": "15",
        }
    )
    assert ok is True
    assert reason == ""

    bad_ok, bad_reason = _validate_site_payload(
        {
            "action": "add",
            "site_name": "Example",
            "base_url": "https://example.com/",
            "platform": "WHMCS",
            "expected_product_number": "0",
        }
    )
    assert bad_ok is False
    assert "Expected Product Number" in bad_reason


def test_apply_site_change_add_edit_delete(tmp_path: Path) -> None:
    sites_path = tmp_path / "sites.json"
    sites_path.write_text('{"sites":{"site":[]}}', encoding="utf-8")

    add_entry = _build_site_entry(
        {
            "site_name": "Demo",
            "base_url": "https://demo.example/",
            "platform": "WHMCS",
            "discoverer": "true",
            "product_scanner": "true",
            "category_scanner": "true",
            "special_crawler": "",
        }
    )
    add_ok, _ = _apply_site_change("add", "Demo", add_entry, str(sites_path))
    assert add_ok is True

    edit_entry = _build_site_entry(
        {
            "site_name": "Demo",
            "base_url": "https://demo2.example/",
            "platform": "HostBill",
            "discoverer": "false",
            "product_scanner": "false",
            "category_scanner": "false",
            "special_crawler": "",
        }
    )
    edit_ok, _ = _apply_site_change("edit", "Demo", edit_entry, str(sites_path))
    assert edit_ok is True

    delete_ok, _ = _apply_site_change("delete", "Demo", {}, str(sites_path))
    assert delete_ok is True
