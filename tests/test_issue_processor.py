from pathlib import Path

from src.main_issue_processor import (
    _apply_site_change,
    _build_site_entry,
    _parse_bool,
    _parse_markdown_form,
    _parse_positive_int,
    _run_site_product_count_test,
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


def test_parse_bool_supports_checkbox_markdown() -> None:
    assert _parse_bool("true") is True
    assert _parse_bool("false") is False
    assert _parse_bool("- [x] Enabled") is True
    assert _parse_bool("- [X] Enabled") is True
    assert _parse_bool("- [ ] Enabled") is False


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


def test_validate_site_payload_rejects_delete_request() -> None:
    ok, reason = _validate_site_payload(
        {
            "action": "delete",
            "site_name": "Example",
            "base_url": "https://example.com/",
            "platform": "WHMCS",
            "expected_product_number": "15",
        }
    )
    assert ok is False
    assert "no longer supports delete" in reason


def test_validate_site_payload_rejects_special_platform() -> None:
    ok, reason = _validate_site_payload(
        {
            "action": "add",
            "site_name": "Example",
            "base_url": "https://example.com/",
            "platform": "SPECIAL",
            "expected_product_number": "15",
        }
    )
    assert ok is False
    assert "Feature Request" in reason


def test_validate_site_payload_rejects_special_crawler() -> None:
    ok, reason = _validate_site_payload(
        {
            "action": "edit",
            "site_name": "Example",
            "base_url": "https://example.com/",
            "platform": "WHMCS",
            "expected_product_number": "15",
            "special_crawler": "acck_api",
        }
    )
    assert ok is False
    assert "Feature Request" in reason


def test_build_site_entry_parses_combined_scanner_checkboxes() -> None:
    entry = _build_site_entry(
        {
            "site_name": "Demo",
            "base_url": "https://demo.example/",
            "platform": "HostBill",
            "scanner_options": (
                "- [x] Enable discoverer\n"
                "- [ ] Enable product scanner\n"
                "- [X] Enable category scanner"
            ),
        }
    )

    assert entry["discoverer"] is True
    assert entry["product_scanner"] is False
    assert entry["category_scanner"] is True
    assert entry["special_crawler"] == ""
    assert entry["category"] == "HostBill"


def test_build_site_entry_keeps_legacy_scanner_fields_compatible() -> None:
    entry = _build_site_entry(
        {
            "site_name": "Demo",
            "base_url": "https://demo.example/",
            "platform": "WHMCS",
            "discoverer": "false",
            "product_scanner": "true",
            "category_scanner": "false",
        }
    )

    assert entry["discoverer"] is False
    assert entry["product_scanner"] is True
    assert entry["category_scanner"] is False


def test_apply_site_change_add_edit(tmp_path: Path) -> None:
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
        }
    )
    edit_ok, _ = _apply_site_change("edit", "Demo", edit_entry, str(sites_path))
    assert edit_ok is True


def test_run_site_product_count_test_uses_whmcs_scan_and_deduplicates(monkeypatch) -> None:
    monkeypatch.setattr("src.main_issue_processor.HttpClient", lambda config: object())
    monkeypatch.setattr(
        "src.main_issue_processor.scan_whmcs_pids",
        lambda site, config, http_client, state_store: [
            {"canonical_url": "https://example.com/a"},
            {"canonical_url": "https://example.com/a"},
            {"canonical_url": "https://example.com/b"},
        ],
    )

    count, method = _run_site_product_count_test(
        {
            "name": "Demo",
            "url": "https://demo.example/",
            "category": "WHMCS",
            "scan_bounds": {},
        },
        2,
        {"scanner": {}},
    )

    assert count == 2
    assert method == "whmcs_pid_scan"


def test_run_site_product_count_test_uses_hostbill_scan_and_deduplicates(monkeypatch) -> None:
    monkeypatch.setattr("src.main_issue_processor.HttpClient", lambda config: object())
    monkeypatch.setattr(
        "src.main_issue_processor.scan_hostbill_pids",
        lambda site, config, http_client, state_store: [
            {"canonical_url": "https://example.com/a"},
            {"canonical_url": "https://example.com/c"},
            {"canonical_url": "https://example.com/c"},
        ],
    )

    count, method = _run_site_product_count_test(
        {
            "name": "Demo",
            "url": "https://demo.example/",
            "category": "HostBill",
            "scan_bounds": {},
        },
        2,
        {"scanner": {}},
    )

    assert count == 2
    assert method == "hostbill_pid_scan"
