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
