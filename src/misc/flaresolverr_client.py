from __future__ import annotations
"""A client for FlareSolverr to bypass Cloudflare and other JS challenges."""

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.misc.logger import get_logger
from src.misc.retry_rate_limit import BackoffPolicy


@dataclass(slots=True)
class FlareSolverrResult:
    """Represents FlareSolverrResult."""
    ok: bool
    status_code: int | None
    final_url: str
    body: str
    cookies: list[dict[str, Any]]
    message: str
    error: str | None = None


class FlareSolverrClient:
    """Represents FlareSolverrClient."""
    def __init__(
        self,
        url: str,
        max_timeout_ms: int = 180000,
        session_ttl_minutes: int = 30,
        retry_attempts: int = 3,
        retry_base_delay_seconds: float = 2.0,
        retry_max_delay_seconds: float = 30.0,
        retry_jitter_seconds: float = 0.5,
    ) -> None:
        """Executes __init__ logic."""
        self.url = url.rstrip("/")
        self.max_timeout_ms = max_timeout_ms
        self.session_ttl_seconds = session_ttl_minutes * 60
        self.backoff = BackoffPolicy(
            max_attempts=max(1, int(retry_attempts)),
            base_delay_seconds=max(0.0, float(retry_base_delay_seconds)),
            max_delay_seconds=max(0.0, float(retry_max_delay_seconds)),
            jitter_seconds=max(0.0, float(retry_jitter_seconds)),
        )
        self._session_cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self.logger = get_logger("flaresolverr")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Executes _post logic."""
        with httpx.Client(timeout=240) as client:
            response = client.post(self.url, json=payload)
            response.raise_for_status()
            return response.json()

    def _create_session(self) -> str:
        """Executes _create_session logic."""
        result = self._post({"cmd": "sessions.create"})
        session_id = result.get("session", "")
        if not session_id:
            raise RuntimeError(f"FlareSolverr session creation failed: {json.dumps(result)[:300]}")
        return session_id

    def _get_or_create_session(self, domain: str) -> str:
        """Executes _get_or_create_session logic."""
        with self._lock:
            cached = self._session_cache.get(domain)
            if cached and (time.time() - cached[1]) < self.session_ttl_seconds:
                return cached[0]

            session_id = self._create_session()
            self._session_cache[domain] = (session_id, time.time())
            return session_id

    @staticmethod
    def _is_retriable_error(error_text: str) -> bool:
        """Executes _is_retriable_error logic."""
        lower = error_text.lower()
        retriable_markers = (
            "timeout",
            "timed out",
            "too many requests",
            "rate limit",
            "429",
            "temporarily unavailable",
            "connection reset",
            "connection refused",
            "read error",
            "network",
            "econnreset",
            "connecterror",
            "readtimeout",
            "connecttimeout",
        )
        return any(marker in lower for marker in retriable_markers)

    def _retry_delay(self, attempt: int) -> float:
        """Executes _retry_delay logic."""
        return self.backoff.delay_for_attempt(attempt)

    def get(self, url: str, domain: str, proxy_url: str | None = None) -> FlareSolverrResult:
        """Executes get logic."""
        max_attempts = self.backoff.max_attempts

        for attempt in range(1, max_attempts + 1):
            try:
                session = self._get_or_create_session(domain)
                payload: dict[str, Any] = {
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": self.max_timeout_ms,
                    "session": session,
                }
                if proxy_url:
                    payload["proxy"] = {"url": proxy_url}

                result = self._post(payload)
                if result.get("status") == "ok":
                    solution = result.get("solution", {})
                    return FlareSolverrResult(
                        ok=True,
                        status_code=solution.get("status"),
                        final_url=solution.get("url", url),
                        body=solution.get("response", ""),
                        cookies=solution.get("cookies", []),
                        message=result.get("message", ""),
                    )

                message = str(result.get("message", "unknown-error"))
                is_retriable = self._is_retriable_error(message)
                if is_retriable and attempt < max_attempts:
                    delay = self._retry_delay(attempt)
                    self.logger.info(
                        "FlareSolverr transient failure for %s: %s; retrying in %.2fs (%s/%s)",
                        url,
                        message,
                        delay,
                        attempt,
                        max_attempts,
                    )
                    time.sleep(delay)
                    continue

                return FlareSolverrResult(
                    ok=False,
                    status_code=None,
                    final_url=url,
                    body="",
                    cookies=[],
                    message=message,
                    error=message,
                )
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                is_retriable = self._is_retriable_error(error_text) or isinstance(
                    exc,
                    (
                        httpx.TimeoutException,
                        httpx.NetworkError,
                    ),
                )
                if is_retriable and attempt < max_attempts:
                    delay = self._retry_delay(attempt)
                    self.logger.info(
                        "FlareSolverr call failed for %s: %s; retrying in %.2fs (%s/%s)",
                        url,
                        exc,
                        delay,
                        attempt,
                        max_attempts,
                    )
                    time.sleep(delay)
                    continue

                self.logger.warning("FlareSolverr call failed for %s: %s", url, exc)
                return FlareSolverrResult(
                    ok=False,
                    status_code=None,
                    final_url=url,
                    body="",
                    cookies=[],
                    message="request-failed",
                    error=error_text,
                )

        return FlareSolverrResult(
            ok=False,
            status_code=None,
            final_url=url,
            body="",
            cookies=[],
            message="request-failed",
            error="retry-exhausted",
        )

