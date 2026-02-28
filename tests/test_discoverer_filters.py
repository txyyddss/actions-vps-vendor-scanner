from __future__ import annotations

from types import SimpleNamespace

from src.discoverer.link_discoverer import LinkDiscoverer
from src.misc.url_normalizer import normalize_url


class FakeHttpClient:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str, force_english: bool = True):  # noqa: ANN001, ARG002
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
        normalize_url("https://example.com/store/vps/basic?currency=2"),
        normalize_url(
            "https://example.com/index.php?currency=8&language=english&rp=%2Fannouncements%2F59%2Fx.html"
        ),
        "https://example.com/cdn-cgi/content?id=123",
        "https://example.com/cart&action=default&languagechange=English",
        "https://example.com/index.php?action=embed&cmd=hbchat",
        "https://example.com/index.php?languagechange=english",
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
              <a href="/store/vps/basic?currency=2">product-currency</a>
              <a href="/index.php?currency=8&language=english&rp=%2Fannouncements%2F59%2Fx.html">route-ann</a>
              <a href="/announcements?language=norwegian">ann</a>
              <a href="/cdn-cgi/content?id=123">cf</a>
              <a href="/cart&action=default&languagechange=English">lang-path</a>
              <a href="/index.php?action=embed&cmd=hbchat">chat</a>
              <a href="/index.php?languagechange=english">lang-change</a>
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
        "https://example.com/": "<html><a href='/index.php?rp=/login'>login</a></html>",
        # Seed URL should still be visited and produce product candidates.
        "https://example.com/cart.php": "<html><a href='/cart.php?a=add&pid=7'>p7</a></html>",
    }
    client = FakeHttpClient(pages)
    discoverer = LinkDiscoverer(http_client=client, max_depth=1, max_pages=10, max_workers=4)
    result = discoverer.discover(site_name="Example", base_url=root)

    assert "https://example.com/cart.php" in client.calls
    assert "https://example.com/cart.php?a=add&pid=7" in result.product_candidates


def test_discoverer_clamps_invalid_worker_count() -> None:
    discoverer = LinkDiscoverer(http_client=FakeHttpClient({}), max_workers=0)
    assert discoverer.max_workers == 1


def test_discoverer_honors_base_href_for_relative_links() -> None:
    pages = {
        "https://example.com/products": """
            <html>
              <head><base href="https://example.com/"></head>
              <body><a href="cart/hk-simplecloud/">category</a></body>
            </html>
        """,
        "https://example.com/cart/hk-simplecloud": "<html></html>",
    }
    client = FakeHttpClient(pages)
    discoverer = LinkDiscoverer(http_client=client, max_depth=1, max_pages=10, max_workers=1)
    result = discoverer.discover(site_name="Example", base_url="https://example.com/products")

    assert "https://example.com/cart/hk-simplecloud" in result.visited_urls
    assert "https://example.com/products/cart/hk-simplecloud" not in result.visited_urls


def test_discoverer_classifies_hostbill_slug_category_from_page_links() -> None:
    root = "https://example.com/cart/hk-simplecloud"
    pages = {
        root: """
            <html>
              <head><base href="https://example.com/"></head>
              <body>
                <h2>HK SimpleCloud</h2>
                <a href="cart/hk--global-route/">global</a>
                <a href="cart/hk--premium-route/">premium</a>
              </body>
            </html>
        """,
        "https://example.com/cart/hk--global-route": "<html></html>",
        "https://example.com/cart/hk--premium-route": "<html></html>",
    }
    client = FakeHttpClient(pages)
    discoverer = LinkDiscoverer(http_client=client, max_depth=0, max_pages=10, max_workers=1)
    result = discoverer.discover(site_name="Example", base_url=root)

    assert result.category_candidates == [root]
    assert result.product_candidates == []


def test_discoverer_classifies_hostbill_slug_product_from_order_form() -> None:
    root = "https://example.com/cart/hk--global-route"
    pages = {
        root: """
            <html>
              <head><base href="https://example.com/"></head>
              <body>
                <h2>HK Global Route</h2>
                <div>$15.00 USD monthly</div>
                <form>
                  <input type="hidden" name="subproducts[0]" value="0">
                  <input type="hidden" name="make" value="order">
                </form>
                <a href="cart/hk-simplecloud/">category</a>
                <a href="cart/hk--premium-route/">sibling</a>
              </body>
            </html>
        """,
    }
    client = FakeHttpClient(pages)
    discoverer = LinkDiscoverer(http_client=client, max_depth=0, max_pages=10, max_workers=1)
    result = discoverer.discover(site_name="Example", base_url=root)

    assert result.product_candidates == [root]
