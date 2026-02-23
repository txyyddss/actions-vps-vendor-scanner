from __future__ import annotations

import time

from src.misc.browser_client import BrowserFetchResult
from src.misc.flaresolverr_client import FlareSolverrResult
from src.misc.http_client import FetchResult, HttpClient


def _build_client() -> HttpClient:
    return HttpClient(
        {
            "http": {"timeout_seconds": 5, "follow_redirects": True, "verify_ssl": True},
            "retry": {
                "max_attempts": 1,
                "base_delay_seconds": 0,
                "max_delay_seconds": 0,
                "jitter_seconds": 0,
            },
            "rate_limit": {
                "global_qps": 1000,
                "per_domain_qps": 1000,
                "default_cooldown_seconds": 0,
                "ratelimit_cooldown_seconds": 0,
                "circuit_breaker_failures": 5,
                "circuit_breaker_cooldown_seconds": 60,
            },
            "flaresolverr": {
                "enabled": True,
                "url": "http://127.0.0.1:8191/v1",
                "max_timeout_ms": 120000,
                "session_ttl_minutes": 30,
            },
            "playwright": {"enabled": True, "headless": True, "timeout_ms": 30000, "wait_until": "load"},
        }
    )


def test_http_client_cloudflare_challenge_falls_back_to_flaresolverr(monkeypatch) -> None:
    client = _build_client()

    monkeypatch.setattr(
        client,
        "_direct_get",
        lambda url, proxy_url=None, cookie_header=None: FetchResult(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=503,
            text="<html><title>Just a moment...</title></html>",
            headers={"server": "cloudflare"},
            tier="direct",
            elapsed_ms=10,
        ),
    )
    monkeypatch.setattr(
        client.flaresolverr,
        "get",
        lambda url, domain, proxy_url=None: FlareSolverrResult(
            ok=True,
            status_code=200,
            final_url=url,
            body="<html>ok</html>",
            cookies=[],
            message="ok",
        ),
    )
    monkeypatch.setattr(
        client.browser,
        "get",
        lambda url, proxy_url=None: BrowserFetchResult(
            ok=False,
            status_code=None,
            final_url=url,
            body="",
            error="browser-should-not-be-used",
        ),
    )

    result = client.get("https://example.com/store", allow_browser_fallback=True)
    assert result.ok is True
    assert result.tier == "flaresolverr"


def test_http_client_browser_fallback_after_flaresolverr_failure(monkeypatch) -> None:
    client = _build_client()

    monkeypatch.setattr(
        client,
        "_direct_get",
        lambda url, proxy_url=None, cookie_header=None: FetchResult(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=403,
            text="<html>Attention Required</html>",
            headers={"server": "cloudflare"},
            tier="direct",
            elapsed_ms=10,
        ),
    )
    monkeypatch.setattr(
        client.flaresolverr,
        "get",
        lambda url, domain, proxy_url=None: FlareSolverrResult(
            ok=False,
            status_code=None,
            final_url=url,
            body="",
            cookies=[],
            message="proxy-failed",
            error="proxy-failed",
        ),
    )
    monkeypatch.setattr(
        client.browser,
        "get",
        lambda url, proxy_url=None: BrowserFetchResult(
            ok=True,
            status_code=200,
            final_url=url,
            body="<html>browser-ok</html>",
            error=None,
        ),
    )

    result = client.get("https://example.com/store", allow_browser_fallback=True)
    assert result.ok is True
    assert result.tier == "browser"


def test_http_client_skips_browser_when_disabled(monkeypatch) -> None:
    client = _build_client()

    monkeypatch.setattr(
        client,
        "_direct_get",
        lambda url, proxy_url=None, cookie_header=None: FetchResult(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=403,
            text="<html>Attention Required</html>",
            headers={"server": "cloudflare"},
            tier="direct",
            elapsed_ms=10,
        ),
    )
    monkeypatch.setattr(
        client.flaresolverr,
        "get",
        lambda url, domain, proxy_url=None: FlareSolverrResult(
            ok=False,
            status_code=None,
            final_url=url,
            body="",
            cookies=[],
            message="proxy-failed",
            error="proxy-failed",
        ),
    )
    monkeypatch.setattr(
        client.browser,
        "get",
        lambda url, proxy_url=None: BrowserFetchResult(
            ok=True,
            status_code=200,
            final_url=url,
            body="<html>browser-ok</html>",
            error=None,
        ),
    )

    result = client.get("https://example.com/store", allow_browser_fallback=False)
    assert result.ok is False
    assert result.tier == "failed"
    assert "proxy-failed" in (result.error or "")


def test_http_client_reuses_cookies_after_flaresolverr_success(monkeypatch) -> None:
    client = _build_client()
    direct_cookie_headers: list[str | None] = []

    def fake_direct_get(url, proxy_url=None, cookie_header=None):  # noqa: ANN001, ARG001
        direct_cookie_headers.append(cookie_header)
        if cookie_header and "cf_clearance=abc123" in cookie_header:
            return FetchResult(
                ok=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                text="<html>direct-ok</html>",
                headers={"server": "cloudflare"},
                tier="direct",
                elapsed_ms=10,
            )
        return FetchResult(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=503,
            text="<html><title>Just a moment...</title></html>",
            headers={"server": "cloudflare"},
            tier="direct",
            elapsed_ms=10,
        )

    monkeypatch.setattr(client, "_direct_get", fake_direct_get)
    monkeypatch.setattr(
        client.flaresolverr,
        "get",
        lambda url, domain, proxy_url=None: FlareSolverrResult(  # noqa: ARG005
            ok=True,
            status_code=200,
            final_url=url,
            body="<html>fs-ok</html>",
            cookies=[
                {
                    "name": "cf_clearance",
                    "value": "abc123",
                    "domain": "example.com",
                    "expires": int(time.time()) + 600,
                }
            ],
            message="ok",
        ),
    )
    monkeypatch.setattr(
        client.browser,
        "get",
        lambda url, proxy_url=None: BrowserFetchResult(  # noqa: ARG005
            ok=False,
            status_code=None,
            final_url=url,
            body="",
            error="browser-should-not-be-used",
        ),
    )

    first = client.get("https://example.com/store", allow_browser_fallback=False)
    second = client.get("https://example.com/store", allow_browser_fallback=False)

    assert first.ok is True
    assert first.tier == "flaresolverr"
    assert second.ok is True
    assert second.tier == "direct"
    assert direct_cookie_headers[0] is None
    assert direct_cookie_headers[1] == "cf_clearance=abc123"


def test_http_client_reuses_browser_cookies_when_flaresolverr_fails(monkeypatch) -> None:
    client = _build_client()
    direct_cookie_headers: list[str | None] = []

    def fake_direct_get(url, proxy_url=None, cookie_header=None):  # noqa: ANN001, ARG001
        direct_cookie_headers.append(cookie_header)
        if cookie_header and "cf_clearance=browser123" in cookie_header:
            return FetchResult(
                ok=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                text="<html>direct-ok</html>",
                headers={"server": "cloudflare"},
                tier="direct",
                elapsed_ms=10,
            )
        return FetchResult(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=503,
            text="<html><title>Just a moment...</title></html>",
            headers={"server": "cloudflare"},
            tier="direct",
            elapsed_ms=10,
        )

    monkeypatch.setattr(client, "_direct_get", fake_direct_get)
    monkeypatch.setattr(
        client.flaresolverr,
        "get",
        lambda url, domain, proxy_url=None: FlareSolverrResult(  # noqa: ARG005
            ok=False,
            status_code=None,
            final_url=url,
            body="",
            cookies=[],
            message="proxy-failed",
            error="proxy-failed",
        ),
    )
    monkeypatch.setattr(
        client.browser,
        "get",
        lambda url, proxy_url=None: BrowserFetchResult(  # noqa: ARG005
            ok=True,
            status_code=200,
            final_url=url,
            body="<html>browser-ok</html>",
            cookies=[
                {
                    "name": "cf_clearance",
                    "value": "browser123",
                    "domain": "example.com",
                    "expires": int(time.time()) + 600,
                }
            ],
            error=None,
        ),
    )

    first = client.get("https://example.com/store", allow_browser_fallback=True)
    second = client.get("https://example.com/store", allow_browser_fallback=False)

    assert first.ok is True
    assert first.tier == "browser"
    assert second.ok is True
    assert second.tier == "direct"
    assert direct_cookie_headers[0] is None
    assert direct_cookie_headers[1] == "cf_clearance=browser123"
