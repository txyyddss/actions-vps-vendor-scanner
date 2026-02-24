from __future__ import annotations
"""A client for FlareSolverr to bypass Cloudflare and other JS challenges."""

import json
import random
import re
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
    _QUEUE_DEPTH_PATTERN = re.compile(r"task queue depth is\s*(\d+)", re.IGNORECASE)

    def __init__(
        self,
        url: str,
        max_timeout_ms: int = 180000,
        session_ttl_minutes: int = 30,
        retry_attempts: int = 3,
        retry_base_delay_seconds: float = 2.0,
        retry_max_delay_seconds: float = 30.0,
        retry_jitter_seconds: float = 0.5,
        queue_depth_threshold: int = 5,
        queue_depth_sleep_seconds: float = 3.0,
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
        self.queue_depth_threshold = max(1, int(queue_depth_threshold))
        self.queue_depth_sleep_seconds = max(0.0, float(queue_depth_sleep_seconds))
        self._request_slot_lock = threading.Lock()
        self._active_request_slots = 0
        self.logger = get_logger("flaresolverr")

    @classmethod
    def _extract_queue_depth(cls, text: str) -> int | None:
        """Extract queue depth from FlareSolverr/Waitress warning text, if present."""
        match = cls._QUEUE_DEPTH_PATTERN.search(text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _acquire_request_slot(self) -> None:
        """Apply client-side queue-depth throttling before submitting a new FS task."""
        while True:
            with self._request_slot_lock:
                depth_after_enqueue = self._active_request_slots + 1
                if depth_after_enqueue <= self.queue_depth_threshold:
                    self._active_request_slots = depth_after_enqueue
                    return
                current_in_flight = self._active_request_slots
            local_delay = random.uniform(0.0, 5.0)
            self.logger.info(
                "FlareSolverr local throttle in_flight=%s cap=%s; sleeping %.1fs before request",
                current_in_flight,
                self.queue_depth_threshold,
                local_delay,
            )
            time.sleep(local_delay)

    def _release_request_slot(self) -> None:
        """Release one previously acquired queue slot."""
        with self._request_slot_lock:
            self._active_request_slots = max(0, self._active_request_slots - 1)

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

    def _invalidate_session(self, domain: str) -> None:
        """Executes _invalidate_session logic."""
        with self._lock:
            self._session_cache.pop(domain, None)

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
            "task queue depth",
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

                self._acquire_request_slot()
                try:
                    result = self._post(payload)
                finally:
                    self._release_request_slot()
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
                queue_depth = self._extract_queue_depth(message)
                if queue_depth is not None and queue_depth > self.queue_depth_threshold:
                    self.logger.warning(
                        "FlareSolverr reported task queue depth %s; sleeping %.1fs before retry",
                        queue_depth,
                        self.queue_depth_sleep_seconds,
                    )
                    time.sleep(self.queue_depth_sleep_seconds)
                is_retriable = self._is_retriable_error(message)

                is_session_error = "session" in message.lower() and (
                    "not found" in message.lower() or
                    "does not exist" in message.lower() or
                    "invalid" in message.lower() or
                    "destroyed" in message.lower()
                )

                if is_session_error:
                    self._invalidate_session(domain)
                    is_retriable = True

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
                queue_depth = self._extract_queue_depth(error_text)
                if queue_depth is not None and queue_depth > self.queue_depth_threshold:
                    self.logger.warning(
                        "FlareSolverr reported task queue depth %s; sleeping %.1fs before retry",
                        queue_depth,
                        self.queue_depth_sleep_seconds,
                    )
                    time.sleep(self.queue_depth_sleep_seconds)
                is_retriable = self._is_retriable_error(error_text) or isinstance(
                    exc,
                    (
                        httpx.TimeoutException,
                        httpx.NetworkError,
                    ),
                )

                is_session_error = "session" in error_text.lower() and (
                    "not found" in error_text.lower() or
                    "does not exist" in error_text.lower() or
                    "invalid" in error_text.lower() or
                    "destroyed" in error_text.lower()
                )

                if is_session_error:
                    self._invalidate_session(domain)
                    is_retriable = True

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

                self.logger.debug("FlareSolverr call failed for %s: %s", url, exc)
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

