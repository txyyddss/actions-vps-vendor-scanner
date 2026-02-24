from src.others.data_merge import diff_products, merge_records


def test_merge_priority_prefers_product_scanner() -> None:
    discoverer = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/store/cat/plan-a",
            "source_priority": "discoverer",
            "stock_status": "unknown",
            "name_raw": "Plan A",
            "name_en": "Plan A",
        }
    ]
    product = [
        {
            "site": "A",
            "platform": "WHMCS",
            "canonical_url": "https://example.com/store/cat/plan-a",
            "source_priority": "product_scanner",
            "stock_status": "in_stock",
            "name_raw": "Plan A Product",
            "name_en": "Plan A Product",
        }
    ]
    category = []

    merged = merge_records(discoverer, product, category, previous_products=[])
    assert len(merged) == 1
    assert merged[0]["source_priority"] == "product_scanner"
    assert merged[0]["name_raw"] == "Plan A Product"


def test_diff_products_detects_add_delete_and_stock_change() -> None:
    old = [
        {"canonical_url": "https://a", "stock_status": "out_of_stock"},
        {"canonical_url": "https://b", "stock_status": "in_stock"},
    ]
    new = [
        {"canonical_url": "https://b", "stock_status": "out_of_stock"},
        {"canonical_url": "https://c", "stock_status": "in_stock"},
    ]
    added, deleted, changed = diff_products(old, new)
    assert added == ["https://c"]
    assert deleted == ["https://a"]
    assert changed == ["https://b"]

