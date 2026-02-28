from __future__ import annotations

from src.misc.config_loader import (
    coerce_positive_int,
    config_string_set,
    config_string_tuple,
    load_cached_config,
    load_cached_config_section,
    reset_cached_config,
)


def test_coerce_positive_int_clamps_invalid_values() -> None:
    assert coerce_positive_int(None, 12) == 12
    assert coerce_positive_int(0, 12) == 1
    assert coerce_positive_int(-9, 12) == 1
    assert coerce_positive_int(25, 12, maximum=8) == 8


def test_load_cached_config_reloads_after_reset(monkeypatch) -> None:
    payloads = iter(
        [
            {"telegram": {"channel_url": "https://t.me/first"}},
            {"telegram": {"channel_url": "https://t.me/second"}},
        ]
    )

    monkeypatch.setattr("src.misc.config_loader.load_json", lambda path: next(payloads))

    reset_cached_config()
    first = load_cached_config()
    second = load_cached_config()
    assert first is second
    assert first["telegram"]["channel_url"] == "https://t.me/first"

    reset_cached_config()
    third = load_cached_config()
    assert third["telegram"]["channel_url"] == "https://t.me/second"
    reset_cached_config()


def test_load_cached_config_section_and_string_helpers(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.misc.config_loader.load_json",
        lambda path: {"demo": {"labels": ["One", "Two"], "routes": ["Alpha", "Beta"]}},
    )

    reset_cached_config()
    assert load_cached_config_section("demo") == {"labels": ["One", "Two"], "routes": ["Alpha", "Beta"]}
    assert config_string_set("demo", "labels", {"fallback"}) == {"one", "two"}
    assert config_string_tuple("demo", "routes", ("fallback",)) == ("alpha", "beta")
    reset_cached_config()
