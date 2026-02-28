from __future__ import annotations

import time

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

    result = client.get("https://example.com/store")
    assert result.ok is True
    assert result.tier == "flaresolverr"


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

    first = client.get("https://example.com/store")
    second = client.get("https://example.com/store")

    assert first.ok is True
    assert first.tier == "flaresolverr"
    assert second.ok is True
    assert second.tier == "direct"
    assert direct_cookie_headers[0] is None
    assert direct_cookie_headers[1] == "cf_clearance=abc123"


def test_http_client_ignores_hostbill_noscript_warning_on_success(monkeypatch) -> None:
    client = _build_client()
    flaresolverr_calls = {"count": 0}

    monkeypatch.setattr(
        client,
        "_direct_get",
        lambda url, proxy_url=None, cookie_header=None: FetchResult(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=200,
            text=(
                "<html><noscript><h1>"
                "To work with the site requires support for JavaScript and Cookies."
                "</h1></noscript><body>ok</body></html>"
            ),
            headers={"server": "cloudflare", "cf-ray": "abc123"},
            tier="direct",
            elapsed_ms=10,
        ),
    )

    def fake_flaresolverr(url, domain, proxy_url=None):  # noqa: ANN001, ARG001
        flaresolverr_calls["count"] += 1
        return FlareSolverrResult(
            ok=True,
            status_code=200,
            final_url=url,
            body="<html>fs-ok</html>",
            cookies=[],
            message="ok",
        )

    monkeypatch.setattr(client.flaresolverr, "get", fake_flaresolverr)

    result = client.get("https://example.com/store")

    assert result.ok is True
    assert result.tier == "direct"
    assert flaresolverr_calls["count"] == 0


def test_http_client_accepts_flaresolverr_no_challenge_content(monkeypatch) -> None:
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
        lambda url, domain, proxy_url=None: FlareSolverrResult(  # noqa: ARG005
            ok=True,
            status_code=200,
            final_url=url,
            body="<html>ok</html>",
            cookies=[],
            message="Challenge not detected!",
        ),
    )

    result = client.get("https://example.com/store")

    assert result.ok is True
    assert result.tier == "flaresolverr"
    assert result.text == "<html>ok</html>"
