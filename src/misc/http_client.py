"""A resilient HTTP fetcher with tiered fallbacks: direct HTTP, FlareSolverr, and Browser."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.misc.flaresolverr_client import FlareSolverrClient
from src.misc.logger import get_logger
from src.misc.retry_rate_limit import (
    RETRIABLE_STATUS_CODES,
    BackoffPolicy,
    CircuitBreaker,
    DomainRateLimiter,
)
from src.misc.url_normalizer import extract_domain, normalize_url


@dataclass(slots=True)
class FetchResult:
    """Represents FetchResult."""

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
    """Tiered fetcher: direct HTTP -> FlareSolverr."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Executes __init__ logic."""
        self.config = config
        self.logger = get_logger("http_client")

        http_cfg = config.get("http", {})
        retry_cfg = config.get("retry", {})
        rate_cfg = config.get("rate_limit", {})
        flaresolverr_cfg = config.get("flaresolverr", {})

        self.timeout = float(http_cfg.get("timeout_seconds", 35))
        self.follow_redirects = bool(http_cfg.get("follow_redirects", True))
        self.verify_ssl = bool(http_cfg.get("verify_ssl", True))
        self.http2 = bool(http_cfg.get("http2", False))
        self.user_agent = http_cfg.get("user_agent", "Mozilla/5.0")
        self.accept_language = http_cfg.get("accept_language", "en-US,en;q=0.9")

        self.backoff = BackoffPolicy(
            max_attempts=int(retry_cfg.get("max_attempts", 3)),
            base_delay_seconds=float(retry_cfg.get("base_delay_seconds", 1.2)),
            max_delay_seconds=float(retry_cfg.get("max_delay_seconds", 30)),
            jitter_seconds=float(retry_cfg.get("jitter_seconds", 0.4)),
        )

        configured_retry_codes = retry_cfg.get("retry_status_codes")
        if isinstance(configured_retry_codes, list):
            self.retry_status_codes: set[int] = {int(c) for c in configured_retry_codes}
        else:
            self.retry_status_codes = set(RETRIABLE_STATUS_CODES)

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
            retry_attempts=int(flaresolverr_cfg.get("retry_attempts", 3)),
            retry_base_delay_seconds=float(flaresolverr_cfg.get("retry_base_delay_seconds", 2.0)),
            retry_max_delay_seconds=float(flaresolverr_cfg.get("retry_max_delay_seconds", 30.0)),
            retry_jitter_seconds=float(flaresolverr_cfg.get("retry_jitter_seconds", 0.5)),
            queue_depth_threshold=int(flaresolverr_cfg.get("queue_depth_threshold", 5)),
            queue_depth_sleep_seconds=float(flaresolverr_cfg.get("queue_depth_sleep_seconds", 3.0)),
        )
        self.flaresolverr_enabled = bool(flaresolverr_cfg.get("enabled", True))
        self.cookie_reuse_enabled = bool(flaresolverr_cfg.get("reuse_cookies", True))
        configured_cookie_ttl = int(
            flaresolverr_cfg.get(
                "cookie_ttl_seconds", int(flaresolverr_cfg.get("session_ttl_minutes", 30)) * 60
            )
        )
        self.cookie_reuse_ttl_seconds = max(60, configured_cookie_ttl)
        self._cookie_lock = threading.Lock()
        self._cookies_by_domain: dict[str, tuple[dict[str, str], float]] = {}

        self.default_proxy_url = ""
        proxy_cfg = config.get("proxy", {})
        if bool(proxy_cfg.get("enabled", False)):
            self.default_proxy_url = str(proxy_cfg.get("url", "")).strip()

    @staticmethod
    def _cookie_domain_matches(request_domain: str, cookie_domain: str) -> bool:
        """Executes _cookie_domain_matches logic."""
        normalized_cookie_domain = cookie_domain.strip().lstrip(".").lower()
        if not normalized_cookie_domain:
            return True
        request_lower = request_domain.lower()
        return request_lower == normalized_cookie_domain or request_lower.endswith(
            f".{normalized_cookie_domain}"
        )

    def _get_cached_cookie_header(self, domain: str) -> str | None:
        """Executes _get_cached_cookie_header logic."""
        if not self.cookie_reuse_enabled:
            return None

        now = time.time()
        with self._cookie_lock:
            cached = self._cookies_by_domain.get(domain)
            if not cached:
                return None
            cookies, expires_at = cached
            if not cookies or expires_at <= now:
                self._cookies_by_domain.pop(domain, None)
                return None
            return "; ".join(f"{name}={value}" for name, value in sorted(cookies.items()))

    def _clear_cached_cookies(self, domain: str) -> None:
        """Executes _clear_cached_cookies logic."""
        with self._cookie_lock:
            self._cookies_by_domain.pop(domain, None)

    def _store_cookies(self, domain: str, cookies: list[dict[str, Any]]) -> None:
        """Executes _store_cookies logic."""
        if not self.cookie_reuse_enabled or not cookies:
            return

        now = time.time()
        merged: dict[str, str] = {}
        with self._cookie_lock:
            cached = self._cookies_by_domain.get(domain)
            if cached and cached[1] > now:
                merged.update(cached[0])

        expires_at = now + self.cookie_reuse_ttl_seconds
        for cookie in cookies:
            name = str(cookie.get("name", "")).strip()
            if not name:
                continue

            cookie_domain = str(cookie.get("domain", "")).strip().lower()
            if cookie_domain and not self._cookie_domain_matches(domain, cookie_domain):
                continue

            raw_value = cookie.get("value")
            if raw_value is None:
                merged.pop(name, None)
                continue

            raw_expires = cookie.get("expires")
            if isinstance(raw_expires, (int, float)) and raw_expires > 0:
                if raw_expires <= now:
                    merged.pop(name, None)
                    continue
                expires_at = min(expires_at, float(raw_expires))

            merged[name] = str(raw_value)

        if not merged:
            self._clear_cached_cookies(domain)
            return

        with self._cookie_lock:
            self._cookies_by_domain[domain] = (merged, expires_at)

    @staticmethod
    def _response_cookies(response: httpx.Response) -> list[dict[str, Any]]:
        """Executes _response_cookies logic."""
        cookies: list[dict[str, Any]] = []
        for cookie in response.cookies.jar:
            cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "expires": cookie.expires,
                }
            )
        return cookies

    @staticmethod
    def _is_cloudflare_like(
        status_code: int | None, text: str, headers: dict[str, str] | None = None
    ) -> bool:
        """Executes _is_cloudflare_like logic."""
        lower = text.lower()
        header_map = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
        strong_markers = (
            "just a moment",
            "attention required",
            "cf-chl",
            "__cf_chl",
            "cf browser verification",
            "cf-browser-verification",
            "challenge-platform",
            "cdn-cgi/challenge-platform",
            "checking your browser before accessing",
            "please stand by, while we are checking your browser",
            "ddos protection by cloudflare",
        )
        weak_markers = (
            "enable javascript and cookies to continue",
            "to work with the site requires support for javascript and cookies",
        )
        has_strong_marker = any(marker in lower for marker in strong_markers)
        has_weak_marker = any(marker in lower for marker in weak_markers)
        has_cloudflare_headers = bool(header_map.get("cf-ray")) or "cloudflare" in header_map.get(
            "server", ""
        )
        if "challenge-platform" in lower or "cdn-cgi/challenge-platform" in lower:
            return True
        if status_code in {403, 429, 503} and (
            has_strong_marker or has_weak_marker or has_cloudflare_headers
        ):
            return True
        if status_code == 200 and has_strong_marker:
            return True
        return False

    @staticmethod
    def _is_success_status(status_code: int | None) -> bool:
        """Return whether a response status is safe to treat as successful content."""
        return status_code is not None and 200 <= status_code < 400

    def _direct_get(
        self, url: str, proxy_url: str | None = None, cookie_header: str | None = None
    ) -> FetchResult:
        """Executes _direct_get logic."""
        start = time.perf_counter()
        headers = {"User-Agent": self.user_agent, "Accept-Language": self.accept_language}
        if cookie_header:
            headers["Cookie"] = cookie_header
        try:
            client_kwargs: dict[str, Any] = {
                "timeout": self.timeout,
                "follow_redirects": self.follow_redirects,
                "verify": self.verify_ssl,
                "http2": self.http2,
                "headers": headers,
            }
            if proxy_url:
                client_kwargs["proxy"] = proxy_url

            try:
                with httpx.Client(**client_kwargs) as client:
                    response = client.get(url)
            except ImportError:
                if not client_kwargs.get("http2"):
                    raise
                client_kwargs["http2"] = False
                self.logger.debug(
                    "http2 extras unavailable for url=%s; retrying direct fetch over HTTP/1.1", url
                )
                with httpx.Client(**client_kwargs) as client:
                    response = client.get(url)

            response_domain = extract_domain(str(response.url)) or extract_domain(url)
            self._store_cookies(response_domain, self._response_cookies(response))

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
        proxy_url: str | None = None,
    ) -> FetchResult:
        """Executes get logic."""
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
        last_status_code: int | None = None
        last_final_url = normalized_url
        last_tier = "failed"
        last_elapsed_ms = 0
        for attempt in range(1, self.backoff.max_attempts + 1):
            should_retry = False
            self.rate_limiter.wait_for_slot(normalized_url)
            cached_cookie_header = self._get_cached_cookie_header(domain)
            direct = self._direct_get(
                url=normalized_url, proxy_url=active_proxy, cookie_header=cached_cookie_header
            )
            self.logger.debug(
                "fetch direct attempt=%s url=%s status=%s elapsed_ms=%s",
                attempt,
                normalized_url,
                direct.status_code,
                direct.elapsed_ms,
            )

            direct_challenge_like = False
            if direct.status_code is not None:
                last_status_code = direct.status_code
                last_final_url = direct.final_url or last_final_url
                last_tier = direct.tier
                last_elapsed_ms = direct.elapsed_ms
                direct_challenge_like = self._is_cloudflare_like(
                    direct.status_code, direct.text, direct.headers
                )
                if direct.status_code == 429:
                    self.rate_limiter.apply_cooldown(
                        normalized_url, self.ratelimit_cooldown_seconds
                    )
                    should_retry = True
                elif not direct_challenge_like and self._is_success_status(direct.status_code):
                    self.circuit_breaker.record_success(domain)
                    return direct
                else:
                    reason = (
                        "cloudflare-like-challenge"
                        if direct_challenge_like
                        else f"status={direct.status_code}"
                    )
                    self.logger.debug(
                        "direct tier fallback url=%s attempt=%s reason=%s",
                        normalized_url,
                        attempt,
                        reason,
                    )
                    if direct_challenge_like and cached_cookie_header:
                        self._clear_cached_cookies(domain)
                    if direct_challenge_like or direct.status_code in self.retry_status_codes:
                        should_retry = True
            elif direct.error:
                should_retry = True

            should_try_flaresolverr = self.flaresolverr_enabled and (
                direct.status_code is None
                or direct_challenge_like
                or direct.status_code in {403, 429}
                or direct.status_code in self.retry_status_codes
            )
            if should_try_flaresolverr:
                fs_start = time.perf_counter()
                fs = self.flaresolverr.get(
                    url=normalized_url, domain=domain, proxy_url=active_proxy
                )
                fs_elapsed = int((time.perf_counter() - fs_start) * 1000)
                self.logger.debug(
                    "fetch flaresolverr attempt=%s url=%s ok=%s status=%s",
                    attempt,
                    normalized_url,
                    fs.ok,
                    fs.status_code,
                )
                if fs.ok:
                    self._store_cookies(domain, fs.cookies)
                if fs.status_code is not None:
                    last_status_code = fs.status_code
                    last_final_url = fs.final_url or last_final_url
                    last_tier = "flaresolverr"
                    last_elapsed_ms = fs_elapsed
                fs_challenge_like = self._is_cloudflare_like(fs.status_code, fs.body, None)
                if fs.ok and self._is_success_status(fs.status_code) and not fs_challenge_like:
                    self.circuit_breaker.record_success(domain)
                    return FetchResult(
                        ok=True,
                        requested_url=normalized_url,
                        final_url=fs.final_url,
                        status_code=fs.status_code,
                        text=fs.body,
                        headers={},
                        tier="flaresolverr",
                        elapsed_ms=fs_elapsed,
                    )
                fs_reason = fs.error
                if not fs_reason:
                    if fs_challenge_like:
                        fs_reason = "cloudflare-like-challenge"
                    elif fs.status_code is not None and not self._is_success_status(fs.status_code):
                        fs_reason = f"status={fs.status_code}"
                    else:
                        fs_reason = fs.message or "flaresolverr-failed"
                last_error = fs_reason
                if (
                    fs_challenge_like
                    or fs.status_code in self.retry_status_codes
                    or (fs.status_code is None and not fs.ok)
                ):
                    should_retry = True
                elif fs.status_code is not None and 400 <= fs.status_code < 500 and fs.status_code != 429:
                    should_retry = False
                self.logger.debug(
                    "flaresolverr tier fallback url=%s attempt=%s reason=%s",
                    normalized_url,
                    attempt,
                    fs_reason,
                )

            # Retry when direct result indicates transient failure.
            if direct.status_code and direct.status_code in self.retry_status_codes:
                self.rate_limiter.apply_cooldown(normalized_url, self.default_cooldown_seconds)
            direct_reason = direct.error
            if not direct_reason and direct.status_code is not None:
                direct_reason = (
                    "cloudflare-like-challenge"
                    if direct_challenge_like
                    else f"status={direct.status_code}"
                )
            last_error = last_error or direct_reason or "fetch-failed"
            if not should_retry:
                break

            if attempt < self.backoff.max_attempts:
                delay = self.backoff.delay_for_attempt(attempt)
                time.sleep(delay)

        if last_status_code is not None and 400 <= last_status_code < 500 and last_status_code != 429:
            self.circuit_breaker.record_success(domain)
        else:
            self.circuit_breaker.record_failure(domain)
        suppress_failure_log = last_status_code == 404 or (
            last_error is not None and "status=404" in last_error
        )
        if not suppress_failure_log:
            if last_error and "500 Internal" in last_error:
                self.logger.debug(
                    "fetch failed completely url=%s reason=%s",
                    normalized_url,
                    last_error or "fetch-failed",
                )
            else:
                self.logger.error(
                    "fetch failed completely url=%s reason=%s",
                    normalized_url,
                    last_error or "fetch-failed",
                )

        return FetchResult(
            ok=False,
            requested_url=normalized_url,
            final_url=last_final_url,
            status_code=last_status_code,
            text="",
            headers={},
            tier=last_tier,
            elapsed_ms=last_elapsed_ms,
            error=last_error or "fetch-failed",
        )
