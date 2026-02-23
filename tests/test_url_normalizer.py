from src.misc.url_normalizer import classify_url, normalize_url


def test_normalize_url_force_english_and_strip_tracking() -> None:
    url = "https://example.com/store/plan-a/?utm_source=x&id=1"
    normalized = normalize_url(url, force_english=True)
    assert "utm_source" not in normalized
    assert "language=english" in normalized
    assert "id=1" in normalized


def test_classify_contact_url_as_invalid() -> None:
    result = classify_url("https://console.po0.com/contact.php")
    assert result.is_invalid_product_url is True
    assert "denylist" in result.reason

