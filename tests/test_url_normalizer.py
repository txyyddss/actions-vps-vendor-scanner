import pytest

from src.misc.url_normalizer import classify_url, normalize_url, should_skip_discovery_url


def test_normalize_url_force_english_and_strip_tracking() -> None:
    url = "https://example.com/store/plan-a/?utm_source=x&id=1"
    normalized = normalize_url(url, force_english=True)
    assert "utm_source" not in normalized
    assert "language=english" in normalized
    assert "id=1" in normalized


def test_normalize_url_force_english_overrides_non_english_language_value() -> None:
    url = "https://example.com/store/plan-a?language=norwegian&id=1"
    normalized = normalize_url(url, force_english=True)
    assert "language=english" in normalized
    assert "language=norwegian" not in normalized


def test_classify_contact_url_as_invalid() -> None:
    result = classify_url("https://console.po0.com/contact.php")
    assert result.is_invalid_product_url is True
    assert "denylist" in result.reason


def test_discovery_skip_non_english_language_url() -> None:
    skip, reason = should_skip_discovery_url("https://console.po0.com/store/vps?language=norwegian")
    assert skip is True
    assert "non-english-language" in reason


def test_discovery_skip_blocked_auth_or_support_path() -> None:
    skip, reason = should_skip_discovery_url("https://example.com/register")
    assert skip is True
    assert "blocked-path" in reason


@pytest.mark.parametrize(
    "path",
    [
        "/login",
        "/password",
        "/register",
        "/contact",
        "/announcements",
        "/knowledgebase",
        "/submitticket",
    ],
)
def test_discovery_skip_requested_blocked_paths(path: str) -> None:
    skip, reason = should_skip_discovery_url(f"https://example.com{path}")
    assert skip is True
    assert "blocked-path" in reason
