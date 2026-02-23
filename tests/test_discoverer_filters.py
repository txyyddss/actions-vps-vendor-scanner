from __future__ import annotations

from types import SimpleNamespace

from src.discoverer.link_discoverer import LinkDiscoverer
from src.misc.url_normalizer import normalize_url


class FakeHttpClient:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str, force_english: bool = True, allow_browser_fallback: bool = True):  # noqa: ANN001, ARG002
        self.calls.append(url)
        html = self.pages.get(url, "<html></html>")
        return SimpleNamespace(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=200,
            text=html,
            headers={},
            tier="direct",
            error=None,
        )


def test_discoverer_skips_non_english_and_utility_paths() -> None:
    root = "https://example.com"
    blocked_urls = {
        "https://example.com/login",
        "https://example.com/password",
        "https://example.com/register",
        "https://example.com/contact",
        "https://example.com/announcements?language=norwegian",
        "https://example.com/knowledgebase",
        "https://example.com/submitticket",
        "https://example.com/supporttickets.php?language=english",
        normalize_url("https://example.com/index.php?currency=8&language=english&rp=%2Fannouncements%2F59%2Fx.html"),
    }
    pages = {
        "https://example.com/": """
            <html>
              <a href="/login">login</a>
              <a href="/password">password</a>
              <a href="/register">register</a>
              <a href="/contact">contact</a>
              <a href="/submitticket">ticket</a>
              <a href="/knowledgebase">kb</a>
              <a href="/supporttickets.php?language=english">supporttickets</a>
              <a href="/index.php?currency=8&language=english&rp=%2Fannouncements%2F59%2Fx.html">route-ann</a>
              <a href="/announcements?language=norwegian">ann</a>
              <a href="/store/vps/basic">product</a>
            </html>
        """,
        "https://example.com/store/vps/basic": "<html></html>",
    }
    client = FakeHttpClient(pages)
    discoverer = LinkDiscoverer(http_client=client, max_depth=1, max_pages=10, max_workers=1)
    result = discoverer.discover(site_name="Example", base_url=root)

    visited = set(result.visited_urls)
    called = set(client.calls)

    for blocked in blocked_urls:
        assert blocked not in visited
        assert blocked not in called

    assert "https://example.com/store/vps/basic" in visited


def test_discoverer_split_candidates_detects_store_category_and_product() -> None:
    urls = {
        "https://example.com/store/hkg-vps",
        "https://example.com/store/hkg-vps/1gb-plan",
        "https://example.com/index.php?rp=%2Fstore%2Fjp-vps",
        "https://example.com/index.php?rp=%2Fstore%2Fjp-vps%2F2gb-plan",
    }
    products, categories = LinkDiscoverer._split_candidates(urls)
    assert "https://example.com/store/hkg-vps" in categories
    assert "https://example.com/store/hkg-vps/1gb-plan" in products
    assert "https://example.com/index.php?rp=%2Fstore%2Fjp-vps" in categories
    assert "https://example.com/index.php?rp=%2Fstore%2Fjp-vps%2F2gb-plan" in products


def test_discoverer_seed_urls_find_catalog_when_root_only_shows_login() -> None:
    root = "https://example.com/"
    pages = {
        # Simulate a login-like landing page with no useful links.
        "https://example.com/?language=english": "<html><a href='/index.php?rp=/login'>login</a></html>",
        # Seed URL should still be visited and produce product candidates.
        "https://example.com/cart.php?language=english": "<html><a href='/cart.php?a=add&pid=7'>p7</a></html>",
    }
    client = FakeHttpClient(pages)
    discoverer = LinkDiscoverer(http_client=client, max_depth=1, max_pages=10, max_workers=4)
    result = discoverer.discover(site_name="Example", base_url=root)

    assert "https://example.com/cart.php?language=english" in client.calls
    assert "https://example.com/cart.php?a=add&pid=7" in result.product_candidates
