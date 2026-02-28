import time

from src.misc.retry_rate_limit import (
    BackoffPolicy,
    CircuitBreaker,
    DomainRateLimiter,
    should_retry_status,
)


def test_should_retry_status() -> None:
    assert should_retry_status(429) is True
    assert should_retry_status(503) is True
    assert should_retry_status(200) is False


def test_backoff_policy_is_increasing() -> None:
    policy = BackoffPolicy(
        max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.2, jitter_seconds=0.0
    )
    assert policy.delay_for_attempt(1) < policy.delay_for_attempt(2)


def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=1)
    domain = "example.com"
    assert breaker.allow(domain) is True
    breaker.record_failure(domain)
    breaker.record_failure(domain)
    assert breaker.allow(domain) is False
    time.sleep(1.1)
    assert breaker.allow(domain) is True


def test_domain_rate_limiter_cooldown() -> None:
    limiter = DomainRateLimiter(global_qps=100, per_domain_qps=100)
    url = "https://example.com/store/plan"
    limiter.apply_cooldown(url, 0.2)
    start = time.perf_counter()
    limiter.wait_for_slot(url)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.18
