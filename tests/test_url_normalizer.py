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


def test_normalize_url_force_english_strips_malformed_amp_language_query_key() -> None:
    url = "https://console.po0.com/store/tencent-can-bgp?amp%3Blanguage=norwegian&language=english"
    normalized = normalize_url(url, force_english=True)
    assert "amp%3Blanguage" not in normalized
    assert normalized.count("language=english") == 1


def test_classify_contact_url_as_invalid() -> None:
    result = classify_url("https://console.po0.com/contact.php")
    assert result.is_invalid_product_url is True
    assert "denylist" in result.reason


def test_discovery_skip_non_english_language_url() -> None:
    skip, reason = should_skip_discovery_url("https://console.po0.com/store/vps?language=norwegian")
    assert skip is True
    assert "non-english-language" in reason


def test_discovery_skip_non_english_language_url_with_malformed_amp_key() -> None:
    skip, reason = should_skip_discovery_url(
        "https://console.po0.com/store/vps?amp%3Blanguage=norwegian"
    )
    assert skip is True
    assert "non-english-language" in reason


def test_discovery_skip_blocked_auth_or_support_path() -> None:
    skip, reason = should_skip_discovery_url("https://example.com/register")
    assert skip is True
    assert "blocked-path" in reason


def test_discovery_skip_currency_query_url() -> None:
    skip, reason = should_skip_discovery_url("https://example.com/store/vps/basic?currency=2")
    assert skip is True
    assert "blocked-query" in reason


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
        "/supporttickets.php",
    ],
)
def test_discovery_skip_requested_blocked_paths(path: str) -> None:
    skip, reason = should_skip_discovery_url(f"https://example.com{path}")
    assert skip is True
    assert "blocked-path" in reason


def test_discovery_skip_rp_announcement_route_url() -> None:
    url = (
        "https://my.rfchost.com/index.php?language=english&"
        "rp=%2Fannouncements%2F59%2FRFCHOST-%E6%97%A5%E6%9C%AC.html"
    )
    skip, reason = should_skip_discovery_url(url)
    assert skip is True
    assert "blocked-route" in reason


def test_discovery_skip_supporttickets_url() -> None:
    skip, reason = should_skip_discovery_url(
        "https://my.rfchost.com/supporttickets.php?language=english"
    )
    assert skip is True
    assert "blocked-path" in reason


def test_discovery_skip_media_url() -> None:
    skip, reason = should_skip_discovery_url(
        "https://backwaves.net/templates/lagom2/assets/img/page-manager/lagom-color-schemes/dark/home-support.png?language=english"
    )
    assert skip is True
    assert "media-or-static-file" in reason


def test_discovery_skip_svg_media_url() -> None:
    skip, reason = should_skip_discovery_url("https://example.com/assets/icon.svg?v=123")
    assert skip is True
    assert "media-or-static-file" in reason
