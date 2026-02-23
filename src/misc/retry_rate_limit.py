from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Final

from src.misc.url_normalizer import extract_domain

RETRIABLE_STATUS_CODES: Final[set[int]] = {408, 425, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class BackoffPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 0.5

    def delay_for_attempt(self, attempt: int) -> float:
        exp_delay = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** max(0, attempt - 1)))
        jitter = random.uniform(0, self.jitter_seconds)
        return exp_delay + jitter


class CircuitBreaker:
    """Simple per-domain circuit breaker to avoid hammering unhealthy targets."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 180) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def allow(self, domain: str) -> bool:
        with self._lock:
            failures, opened_at = self._state.get(domain, (0, 0.0))
            if failures < self.failure_threshold:
                return True
            if (time.time() - opened_at) > self.cooldown_seconds:
                self._state[domain] = (0, 0.0)
                return True
            return False

    def record_success(self, domain: str) -> None:
        with self._lock:
            self._state[domain] = (0, 0.0)

    def record_failure(self, domain: str) -> None:
        with self._lock:
            failures, opened_at = self._state.get(domain, (0, 0.0))
            failures += 1
            if failures >= self.failure_threshold and opened_at == 0.0:
                opened_at = time.time()
            self._state[domain] = (failures, opened_at)


class DomainRateLimiter:
    """Token-bucket-like limiter using minimum spacing between domain calls."""

    def __init__(self, global_qps: float = 4.0, per_domain_qps: float = 1.0) -> None:
        self.global_interval = 1.0 / max(0.01, global_qps)
        self.per_domain_interval = 1.0 / max(0.01, per_domain_qps)
        self._lock = threading.Lock()
        self._last_global = 0.0
        self._last_domain: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}

    def wait_for_slot(self, url: str) -> None:
        domain = extract_domain(url)
        while True:
            wait_seconds = 0.0
            with self._lock:
                now = time.time()
                cooldown = self._cooldown_until.get(domain, 0.0)
                if cooldown > now:
                    wait_seconds = max(wait_seconds, cooldown - now)

                since_global = now - self._last_global
                if since_global < self.global_interval:
                    wait_seconds = max(wait_seconds, self.global_interval - since_global)

                since_domain = now - self._last_domain.get(domain, 0.0)
                if since_domain < self.per_domain_interval:
                    wait_seconds = max(wait_seconds, self.per_domain_interval - since_domain)

                if wait_seconds <= 0:
                    self._last_global = now
                    self._last_domain[domain] = now
                    return

            time.sleep(min(wait_seconds, 0.5))

    def apply_cooldown(self, url: str, seconds: float) -> None:
        domain = extract_domain(url)
        with self._lock:
            self._cooldown_until[domain] = max(self._cooldown_until.get(domain, 0.0), time.time() + seconds)


def should_retry_status(status_code: int) -> bool:
    return status_code in RETRIABLE_STATUS_CODES

