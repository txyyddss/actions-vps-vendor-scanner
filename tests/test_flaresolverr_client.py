import httpx

from src.misc.flaresolverr_client import FlareSolverrClient


def test_flaresolverr_success(monkeypatch) -> None:
    client = FlareSolverrClient("http://127.0.0.1:8191/v1")

    responses = [
        {"status": "ok", "session": "sess-1"},
        {
            "status": "ok",
            "message": "Challenge solved!",
            "solution": {
                "status": 200,
                "url": "https://target.example/store",
                "response": "<html>ok</html>",
                "cookies": [],
            },
        },
    ]

    def fake_post(_payload):
        return responses.pop(0)

    monkeypatch.setattr(client, "_post", fake_post)
    result = client.get("https://target.example/store", domain="target.example")
    assert result.ok is True
    assert result.status_code == 200
    assert result.final_url == "https://target.example/store"


def test_flaresolverr_error_response(monkeypatch) -> None:
    client = FlareSolverrClient("http://127.0.0.1:8191/v1")
    monkeypatch.setattr(client, "_get_or_create_session", lambda _domain: "sess-1")

    call_count = {"count": 0}

    def fake_post(_payload):
        call_count["count"] += 1
        return {"status": "error", "message": "proxy-failed"}

    monkeypatch.setattr(client, "_post", fake_post)
    result = client.get("https://target.example/store", domain="target.example")
    assert result.ok is False
    assert "proxy-failed" in (result.error or result.message)
    assert call_count["count"] == 1


def test_flaresolverr_no_challenge_with_solution_is_success(monkeypatch) -> None:
    client = FlareSolverrClient("http://127.0.0.1:8191/v1")
    monkeypatch.setattr(client, "_get_or_create_session", lambda _domain: "sess-1")

    monkeypatch.setattr(
        client,
        "_post",
        lambda _payload: {
            "status": "error",
            "message": "Challenge not detected!",
            "solution": {
                "status": 200,
                "url": "https://target.example/store",
                "response": "<html>ok</html>",
                "cookies": [],
            },
        },
    )

    result = client.get("https://target.example/store", domain="target.example")

    assert result.ok is True
    assert result.status_code == 200
    assert result.final_url == "https://target.example/store"
    assert result.body == "<html>ok</html>"


def test_flaresolverr_retries_timeout_then_succeeds(monkeypatch) -> None:
    client = FlareSolverrClient(
        "http://127.0.0.1:8191/v1",
        retry_attempts=3,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
        retry_jitter_seconds=0,
    )
    monkeypatch.setattr(client, "_get_or_create_session", lambda _domain: "sess-1")

    call_count = {"count": 0}

    def fake_post(_payload):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise httpx.ReadTimeout("timed out")
        return {
            "status": "ok",
            "message": "Challenge solved!",
            "solution": {
                "status": 200,
                "url": "https://target.example/store",
                "response": "<html>ok</html>",
                "cookies": [],
            },
        }

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "src.misc.flaresolverr_client.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )
    monkeypatch.setattr(client, "_post", fake_post)

    result = client.get("https://target.example/store", domain="target.example")
    assert result.ok is True
    assert call_count["count"] == 2
    assert len(sleep_calls) == 1


def test_flaresolverr_retries_retriable_error_response(monkeypatch) -> None:
    client = FlareSolverrClient(
        "http://127.0.0.1:8191/v1",
        retry_attempts=3,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
        retry_jitter_seconds=0,
    )
    monkeypatch.setattr(client, "_get_or_create_session", lambda _domain: "sess-1")

    responses = [
        {"status": "error", "message": "Too many requests"},
        {
            "status": "ok",
            "message": "Challenge solved!",
            "solution": {
                "status": 200,
                "url": "https://target.example/store",
                "response": "<html>ok</html>",
                "cookies": [],
            },
        },
    ]

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "src.misc.flaresolverr_client.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )
    monkeypatch.setattr(client, "_post", lambda _payload: responses.pop(0))

    result = client.get("https://target.example/store", domain="target.example")
    assert result.ok is True
    assert len(sleep_calls) == 1


def test_flaresolverr_queue_guard_sleeps_when_depth_too_high(monkeypatch) -> None:
    client = FlareSolverrClient(
        "http://127.0.0.1:8191/v1",
        queue_depth_threshold=5,
        queue_depth_sleep_seconds=2.0,
    )
    with client._request_slot_lock:
        client._active_request_slots = 6

    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        with client._request_slot_lock:
            client._active_request_slots = 4

    monkeypatch.setattr("src.misc.flaresolverr_client.random.uniform", lambda low, high: 1.25)  # noqa: ARG005
    monkeypatch.setattr("src.misc.flaresolverr_client.time.sleep", fake_sleep)

    client._acquire_request_slot()
    with client._request_slot_lock:
        active_after_acquire = client._active_request_slots
    client._release_request_slot()
    with client._request_slot_lock:
        active_after_release = client._active_request_slots

    assert sleep_calls == [1.25]
    assert active_after_acquire == 5
    assert active_after_release == 4


def test_flaresolverr_retries_queue_depth_error_response(monkeypatch) -> None:
    client = FlareSolverrClient(
        "http://127.0.0.1:8191/v1",
        retry_attempts=3,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
        retry_jitter_seconds=0,
        queue_depth_threshold=5,
        queue_depth_sleep_seconds=2.0,
    )
    monkeypatch.setattr(client, "_get_or_create_session", lambda _domain: "sess-1")

    responses = [
        {"status": "error", "message": "Task queue depth is 90"},
        {
            "status": "ok",
            "message": "Challenge solved!",
            "solution": {
                "status": 200,
                "url": "https://target.example/store",
                "response": "<html>ok</html>",
                "cookies": [],
            },
        },
    ]

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "src.misc.flaresolverr_client.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )
    monkeypatch.setattr(client, "_post", lambda _payload: responses.pop(0))

    result = client.get("https://target.example/store", domain="target.example")
    assert result.ok is True
    assert 2.0 in sleep_calls
