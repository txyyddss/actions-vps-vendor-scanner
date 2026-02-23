from __future__ import annotations

from pathlib import Path

from src.main_scanner import _product_mode
from src.others.state_store import StateStore


class DummyHttpClient:
    pass


def test_product_mode_skips_special_crawler_when_product_scanner_disabled(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr("src.main_scanner._save_tmp", lambda name, payload: None)  # noqa: ARG005

    def fake_acck_api(site, http_client):  # noqa: ANN001, ARG001
        calls.append(site["name"])
        return [{"canonical_url": "https://acck.io/x"}]

    monkeypatch.setattr("src.main_scanner.scan_acck_api", fake_acck_api)

    sites = [
        {
            "enabled": True,
            "name": "ACCK",
            "url": "https://acck.io/",
            "special_crawler": "acck_api",
            "category": "SPECIAL",
            "product_scanner": False,
            "scan_bounds": {},
        }
    ]
    config = {"scanner": {"max_workers": 1}}
    rows = _product_mode(sites, config, DummyHttpClient(), StateStore(tmp_path / "state.json"))

    assert rows == []
    assert calls == []


def test_product_mode_runs_special_crawler_when_product_scanner_enabled(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr("src.main_scanner._save_tmp", lambda name, payload: None)  # noqa: ARG005

    def fake_acck_api(site, http_client):  # noqa: ANN001, ARG001
        calls.append(site["name"])
        return [{"canonical_url": "https://acck.io/x"}]

    monkeypatch.setattr("src.main_scanner.scan_acck_api", fake_acck_api)

    sites = [
        {
            "enabled": True,
            "name": "ACCK",
            "url": "https://acck.io/",
            "special_crawler": "acck_api",
            "category": "SPECIAL",
            "product_scanner": True,
            "scan_bounds": {},
        }
    ]
    config = {"scanner": {"max_workers": 1}}
    rows = _product_mode(sites, config, DummyHttpClient(), StateStore(tmp_path / "state.json"))

    assert len(rows) == 1
    assert calls == ["ACCK"]
