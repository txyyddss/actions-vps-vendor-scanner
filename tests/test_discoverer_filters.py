from __future__ import annotations

from types import SimpleNamespace

from src.discoverer.link_discoverer import LinkDiscoverer


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
