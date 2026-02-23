from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.misc.browser_client import BrowserClient
from src.misc.flaresolverr_client import FlareSolverrClient
from src.misc.logger import get_logger
from src.misc.retry_rate_limit import BackoffPolicy, CircuitBreaker, DomainRateLimiter, should_retry_status
from src.misc.url_normalizer import extract_domain, normalize_url


@dataclass(slots=True)
class FetchResult:
    ok: bool
    requested_url: str
    final_url: str
    status_code: int | None
    text: str
    headers: dict[str, str]
    tier: str
    elapsed_ms: int
    error: str | None = None


class HttpClient:
    """Tiered fetcher: direct HTTP -> FlareSolverr -> Playwright."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.logger = get_logger("http_client")

        http_cfg = config.get("http", {})
        retry_cfg = config.get("retry", {})
        rate_cfg = config.get("rate_limit", {})
        flaresolverr_cfg = config.get("flaresolverr", {})
        playwright_cfg = config.get("playwright", {})

        self.timeout = float(http_cfg.get("timeout_seconds", 35))
        self.follow_redirects = bool(http_cfg.get("follow_redirects", True))
        self.verify_ssl = bool(http_cfg.get("verify_ssl", True))
        self.user_agent = http_cfg.get("user_agent", "Mozilla/5.0")
        self.accept_language = http_cfg.get("accept_language", "en-US,en;q=0.9")

        self.backoff = BackoffPolicy(
            max_attempts=int(retry_cfg.get("max_attempts", 3)),
            base_delay_seconds=float(retry_cfg.get("base_delay_seconds", 1.2)),
            max_delay_seconds=float(retry_cfg.get("max_delay_seconds", 30)),
            jitter_seconds=float(retry_cfg.get("jitter_seconds", 0.4)),
        )

        self.default_cooldown_seconds = float(rate_cfg.get("default_cooldown_seconds", 45))
        self.ratelimit_cooldown_seconds = float(rate_cfg.get("ratelimit_cooldown_seconds", 90))
        self.rate_limiter = DomainRateLimiter(
            global_qps=float(rate_cfg.get("global_qps", 4)),
            per_domain_qps=float(rate_cfg.get("per_domain_qps", 1)),
        )
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=int(rate_cfg.get("circuit_breaker_failures", 5)),
            cooldown_seconds=int(rate_cfg.get("circuit_breaker_cooldown_seconds", 180)),
        )

        self.flaresolverr = FlareSolverrClient(
            url=flaresolverr_cfg.get("url", "http://127.0.0.1:8191/v1"),
            max_timeout_ms=int(flaresolverr_cfg.get("max_timeout_ms", 180000)),
            session_ttl_minutes=int(flaresolverr_cfg.get("session_ttl_minutes", 30)),
        )
        self.flaresolverr_enabled = bool(flaresolverr_cfg.get("enabled", True))

        self.browser = BrowserClient(
            enabled=bool(playwright_cfg.get("enabled", True)),
            headless=bool(playwright_cfg.get("headless", True)),
            timeout_ms=int(playwright_cfg.get("timeout_ms", 60000)),
            wait_until=str(playwright_cfg.get("wait_until", "networkidle")),
        )

        self.default_proxy_url = ""
        proxy_cfg = config.get("proxy", {})
        if bool(proxy_cfg.get("enabled", False)):
            self.default_proxy_url = str(proxy_cfg.get("url", "")).strip()

    @staticmethod
    def _is_cloudflare_like(status_code: int | None, text: str) -> bool:
        lower = text.lower()
        markers = ("just a moment", "cf-chl", "cloudflare", "attention required")
        return (status_code in {403, 503} and any(marker in lower for marker in markers)) or (
            "challenge-platform" in lower
        )

    def _direct_get(self, url: str, proxy_url: str | None = None) -> FetchResult:
        start = time.perf_counter()
        headers = {"User-Agent": self.user_agent, "Accept-Language": self.accept_language}
        try:
            client_kwargs: dict[str, Any] = {
                "timeout": self.timeout,
                "follow_redirects": self.follow_redirects,
                "verify": self.verify_ssl,
                "headers": headers,
            }
            if proxy_url:
                client_kwargs["proxy"] = proxy_url

            with httpx.Client(**client_kwargs) as client:
                response = client.get(url)

            elapsed = int((time.perf_counter() - start) * 1000)
            return FetchResult(
                ok=True,
                requested_url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                text=response.text,
                headers=dict(response.headers),
                tier="direct",
                elapsed_ms=elapsed,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.perf_counter() - start) * 1000)
            return FetchResult(
                ok=False,
                requested_url=url,
                final_url=url,
                status_code=None,
                text="",
                headers={},
                tier="direct",
                elapsed_ms=elapsed,
                error=str(exc),
            )

    def get(
        self,
        url: str,
        force_english: bool = True,
        allow_browser_fallback: bool = True,
        proxy_url: str | None = None,
    ) -> FetchResult:
        normalized_url = normalize_url(url, force_english=force_english)
        domain = extract_domain(normalized_url)
        active_proxy = proxy_url or self.default_proxy_url or None

        if not self.circuit_breaker.allow(domain):
            return FetchResult(
                ok=False,
                requested_url=normalized_url,
                final_url=normalized_url,
                status_code=None,
                text="",
                headers={},
                tier="circuit-breaker",
                elapsed_ms=0,
                error=f"circuit-open:{domain}",
            )

        last_error: str | None = None
        for attempt in range(1, self.backoff.max_attempts + 1):
            self.rate_limiter.wait_for_slot(normalized_url)
            direct = self._direct_get(url=normalized_url, proxy_url=active_proxy)
            self.logger.info(
                "fetch direct attempt=%s url=%s status=%s elapsed_ms=%s",
                attempt,
                normalized_url,
                direct.status_code,
                direct.elapsed_ms,
            )

            if direct.ok and direct.status_code is not None:
                if direct.status_code == 429:
                    self.rate_limiter.apply_cooldown(normalized_url, self.ratelimit_cooldown_seconds)
                elif not self._is_cloudflare_like(direct.status_code, direct.text) and direct.status_code < 500:
                    self.circuit_breaker.record_success(domain)
                    return direct

            if self.flaresolverr_enabled:
                fs = self.flaresolverr.get(url=normalized_url, domain=domain, proxy_url=active_proxy)
                self.logger.info(
                    "fetch flaresolverr attempt=%s url=%s ok=%s status=%s",
                    attempt,
                    normalized_url,
                    fs.ok,
                    fs.status_code,
                )
                if fs.ok and not self._is_cloudflare_like(fs.status_code, fs.body):
                    self.circuit_breaker.record_success(domain)
                    return FetchResult(
                        ok=True,
                        requested_url=normalized_url,
                        final_url=fs.final_url,
                        status_code=fs.status_code,
                        text=fs.body,
                        headers={},
                        tier="flaresolverr",
                        elapsed_ms=0,
                    )
                last_error = fs.error or fs.message

            if allow_browser_fallback:
                browser = self.browser.get(url=normalized_url, proxy_url=active_proxy)
                self.logger.info(
                    "fetch browser attempt=%s url=%s ok=%s status=%s",
                    attempt,
                    normalized_url,
                    browser.ok,
                    browser.status_code,
                )
                if browser.ok and browser.body:
                    self.circuit_breaker.record_success(domain)
                    return FetchResult(
                        ok=True,
                        requested_url=normalized_url,
                        final_url=browser.final_url,
                        status_code=browser.status_code,
                        text=browser.body,
                        headers={},
                        tier="browser",
                        elapsed_ms=0,
                    )
                last_error = browser.error or last_error

            # Retry when direct result indicates transient failure.
            if direct.status_code and should_retry_status(direct.status_code):
                self.rate_limiter.apply_cooldown(normalized_url, self.default_cooldown_seconds)
            delay = self.backoff.delay_for_attempt(attempt)
            time.sleep(delay)
            last_error = last_error or direct.error or f"status={direct.status_code}"

        self.circuit_breaker.record_failure(domain)
        return FetchResult(
            ok=False,
            requested_url=normalized_url,
            final_url=normalized_url,
            status_code=None,
            text="",
            headers={},
            tier="failed",
            elapsed_ms=0,
            error=last_error or "fetch-failed",
        )

