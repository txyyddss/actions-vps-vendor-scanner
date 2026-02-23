from pathlib import Path

from src.main_issue_processor import (
    _apply_site_change,
    _parse_markdown_form,
    _validate_site_payload,
)


def test_parse_markdown_form() -> None:
    body = """### Action
add
### Site Name
Example
### Base URL
https://example.com/
"""
    fields = _parse_markdown_form(body)
    assert fields["action"] == "add"
    assert fields["site_name"] == "Example"
    assert fields["base_url"] == "https://example.com/"


def test_validate_site_payload() -> None:
    ok, reason = _validate_site_payload(
        {
            "action": "add",
            "site_name": "Example",
            "base_url": "https://example.com/",
        }
    )
    assert ok is True
    assert reason == ""


def test_apply_site_change_add_edit_delete(tmp_path: Path) -> None:
    sites_path = tmp_path / "sites.json"
    sites_path.write_text('{"sites":{"site":[]}}', encoding="utf-8")

    add_ok, _ = _apply_site_change(
        {
            "action": "add",
            "site_name": "Demo",
            "base_url": "https://demo.example/",
            "platform": "WHMCS",
            "discoverer": "true",
            "product_scanner": "true",
            "category_scanner": "true",
            "special_crawler": "",
        },
        str(sites_path),
    )
    assert add_ok is True

    edit_ok, _ = _apply_site_change(
        {
            "action": "edit",
            "site_name": "Demo",
            "base_url": "https://demo2.example/",
            "platform": "HostBill",
            "discoverer": "false",
            "product_scanner": "false",
            "category_scanner": "false",
            "special_crawler": "",
        },
        str(sites_path),
    )
    assert edit_ok is True

    delete_ok, _ = _apply_site_change(
        {
            "action": "delete",
            "site_name": "Demo",
            "base_url": "https://demo2.example/",
        },
        str(sites_path),
    )
    assert delete_ok is True

