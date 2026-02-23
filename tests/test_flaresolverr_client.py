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
    responses = [
        {"status": "ok", "session": "sess-1"},
        {"status": "error", "message": "proxy-failed"},
    ]

    def fake_post(_payload):
        return responses.pop(0)

    monkeypatch.setattr(client, "_post", fake_post)
    result = client.get("https://target.example/store", domain="target.example")
    assert result.ok is False
    assert "proxy-failed" in (result.error or result.message)

