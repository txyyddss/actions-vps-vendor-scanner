from src.others.data_merge import diff_products, merge_records


def test_merge_priority_prefers_product_scanner() -> None:
    discoverer = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/store/cat/plan-a",
            "scan_type": "discoverer",
            "in_stock": -1,
            "name_raw": "Plan A",
        }
    ]
    product = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/store/cat/plan-a",
            "scan_type": "product_scanner",
            "in_stock": 1,
            "name_raw": "Plan A Product",
        }
    ]
    category = []

    merged = merge_records(discoverer, product, category, previous_products=[])
    assert len(merged) == 1
    assert merged[0]["scan_type"] == "product_scanner"
    assert merged[0]["name_raw"] == "Plan A Product"
    assert merged[0]["in_stock"] == 1


def test_diff_products_detects_add_delete_and_stock_change() -> None:
    old = [
        {"canonical_url": "https://a", "in_stock": 0},
        {"canonical_url": "https://b", "in_stock": 1},
    ]
    new = [
        {"canonical_url": "https://b", "in_stock": 0},
        {"canonical_url": "https://c", "in_stock": 1},
    ]
    added, deleted, changed = diff_products(old, new)
    assert added == ["https://c"]
    assert deleted == ["https://a"]
    assert changed == ["https://b"]


def test_merge_same_content_dedup() -> None:
    """Products with same name_raw, description_raw, site should be merged."""
    records = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/cart.php?a=add&pid=1",
            "scan_type": "product_scanner",
            "in_stock": 1,
            "name_raw": "VPS Plan",
            "description_raw": "A great VPS plan",
            "evidence": ["confproduct-final-url"],
        },
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/cart.php?a=add&pid=2",
            "scan_type": "product_scanner",
            "in_stock": 1,
            "name_raw": "VPS Plan",
            "description_raw": "A great VPS plan",
            "evidence": ["confproduct-final-url"],
        },
    ]

    merged = merge_records([], records, [], previous_products=[])
    assert len(merged) == 1
    assert "content-dedup-merged" in merged[0]["evidence"]


def test_merge_skips_oos_marker_for_dedup() -> None:
    """Products with oos-marker evidence should not be content-deduplicated."""
    records = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/cart.php?a=add&pid=1",
            "scan_type": "product_scanner",
            "in_stock": 0,
            "name_raw": "VPS Plan",
            "description_raw": "Out of Stock",
            "evidence": ["oos-marker"],
        },
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/cart.php?a=add&pid=2",
            "scan_type": "product_scanner",
            "in_stock": 0,
            "name_raw": "VPS Plan",
            "description_raw": "Out of Stock",
            "evidence": ["oos-marker"],
        },
    ]

    merged = merge_records([], records, [], previous_products=[])
    assert len(merged) == 2


def test_legacy_stock_status_converted_to_in_stock() -> None:
    """Legacy stock_status string should be converted to in_stock integer."""
    records = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/cart.php?a=add&pid=1",
            "scan_type": "product_scanner",
            "stock_status": "in_stock",
            "name_raw": "Plan",
        },
    ]
    merged = merge_records([], records, [], previous_products=[])
    assert merged[0]["in_stock"] == 1


def test_numeric_string_stock_values_are_normalized() -> None:
    records = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/cart.php?a=add&pid=1",
            "scan_type": "product_scanner",
            "in_stock": "0",
            "name_raw": "Plan",
        },
    ]

    merged = merge_records([], records, [], previous_products=[])
    assert merged[0]["in_stock"] == 0


def test_diff_products_ignores_equivalent_mixed_stock_formats() -> None:
    old = [{"canonical_url": "https://a", "in_stock": "1"}]
    new = [{"canonical_url": "https://a", "stock_status": "in_stock"}]

    added, deleted, changed = diff_products(old, new)

    assert added == []
    assert deleted == []
    assert changed == []


def test_write_and_load_site_grouped_roundtrip(tmp_path) -> None:
    """write_products produces site-grouped JSON; load_products inflates back to flat list."""
    import json

    from src.others.data_merge import load_products, write_products

    products = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://a.example/p1",
            "scan_type": "product_scanner",
            "in_stock": 1,
            "name_raw": "Plan 1",
            "type": "product",
        },
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://a.example/c1",
            "scan_type": "category_scanner",
            "in_stock": -1,
            "name_raw": "Category 1",
            "type": "category",
        },
        {
            "site": "B",
            "platform": "HostBill",
            "canonical_url": "https://b.example/p2",
            "scan_type": "product_scanner",
            "in_stock": 0,
            "name_raw": "Plan 2",
            "type": "product",
        },
    ]
    path = str(tmp_path / "products.json")
    write_products(products, run_id="test-run", path=path)

    # Verify JSON structure
    raw = json.loads((tmp_path / "products.json").read_text())
    assert "sites" in raw
    assert "products" not in raw  # No flat products at root
    assert len(raw["sites"]) == 2
    site_a = next(s for s in raw["sites"] if s["site"] == "A")
    assert len(site_a["products"]) == 1
    assert len(site_a["categories"]) == 1
    assert site_a["product_count"] == 1
    assert site_a["platform"] == "WHMCS"
    # Nested records should NOT have site/platform
    assert "site" not in site_a["products"][0]
    assert "platform" not in site_a["products"][0]

    # Round-trip: load should inflate back to flat list with site/platform
    loaded = load_products(path)
    assert len(loaded) == 3
    urls = {item["canonical_url"] for item in loaded}
    assert urls == {"https://a.example/p1", "https://a.example/c1", "https://b.example/p2"}
    for item in loaded:
        assert "site" in item
        assert "platform" in item
