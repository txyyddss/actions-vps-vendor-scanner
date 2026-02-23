from __future__ import annotations

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
        lambda url, proxy_url=None: FetchResult(
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
        lambda url, proxy_url=None: FetchResult(
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
        lambda url, proxy_url=None: FetchResult(
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
