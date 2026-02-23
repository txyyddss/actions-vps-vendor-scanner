from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.misc.logger import get_logger


@dataclass(slots=True)
class FlareSolverrResult:
    ok: bool
    status_code: int | None
    final_url: str
    body: str
    cookies: list[dict[str, Any]]
    message: str
    error: str | None = None


class FlareSolverrClient:
    def __init__(self, url: str, max_timeout_ms: int = 180000, session_ttl_minutes: int = 30) -> None:
        self.url = url.rstrip("/")
        self.max_timeout_ms = max_timeout_ms
        self.session_ttl_seconds = session_ttl_minutes * 60
        self._session_cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self.logger = get_logger("flaresolverr")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=240) as client:
            response = client.post(self.url, json=payload)
            response.raise_for_status()
            return response.json()

    def _create_session(self) -> str:
        result = self._post({"cmd": "sessions.create"})
        session_id = result.get("session", "")
        if not session_id:
            raise RuntimeError(f"FlareSolverr session creation failed: {json.dumps(result)[:300]}")
        return session_id

    def _get_or_create_session(self, domain: str) -> str:
        with self._lock:
            cached = self._session_cache.get(domain)
            if cached and (time.time() - cached[1]) < self.session_ttl_seconds:
                return cached[0]

            session_id = self._create_session()
            self._session_cache[domain] = (session_id, time.time())
            return session_id

    def get(self, url: str, domain: str, proxy_url: str | None = None) -> FlareSolverrResult:
        session = self._get_or_create_session(domain)
        payload: dict[str, Any] = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": self.max_timeout_ms,
            "session": session,
        }
        if proxy_url:
            payload["proxy"] = {"url": proxy_url}

        try:
            result = self._post(payload)
            if result.get("status") != "ok":
                return FlareSolverrResult(
                    ok=False,
                    status_code=None,
                    final_url=url,
                    body="",
                    cookies=[],
                    message=result.get("message", "unknown-error"),
                    error=result.get("message"),
                )

            solution = result.get("solution", {})
            return FlareSolverrResult(
                ok=True,
                status_code=solution.get("status"),
                final_url=solution.get("url", url),
                body=solution.get("response", ""),
                cookies=solution.get("cookies", []),
                message=result.get("message", ""),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("FlareSolverr call failed for %s: %s", url, exc)
            return FlareSolverrResult(
                ok=False,
                status_code=None,
                final_url=url,
                body="",
                cookies=[],
                message="request-failed",
                error=str(exc),
            )

