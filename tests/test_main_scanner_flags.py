from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from src.main_scanner import _discover_mode
from src.main_scanner import _product_mode
from src.others.state_store import StateStore


class DummyHttpClient:
    pass


def test_product_mode_runs_special_crawler_even_when_product_scanner_disabled(monkeypatch, tmp_path: Path) -> None:
    """Special crawlers (acck_api, akile_api) should run regardless of product_scanner flag."""
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

    assert len(rows) == 1
    assert calls == ["ACCK"]


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


def test_discover_mode_runs_sites_in_parallel_and_each_site_single_worker(monkeypatch) -> None:
    monkeypatch.setattr("src.main_scanner._save_tmp", lambda name, payload: None)  # noqa: ARG005

    lock = threading.Lock()
    active = 0
    max_active = 0
    observed_max_workers: list[int] = []

    class FakeDiscoverer:
        def __init__(self, http_client, max_depth, max_pages, max_workers):  # noqa: ANN001, ARG002
            observed_max_workers.append(max_workers)

        def discover(self, site_name: str, base_url: str):  # noqa: ANN001
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return SimpleNamespace(
                site_name=site_name,
                base_url=base_url,
                visited_urls=[],
                product_candidates=[f"{base_url}product"],
                category_candidates=[],
            )

    monkeypatch.setattr("src.main_scanner.LinkDiscoverer", FakeDiscoverer)

    config = {
        "scanner": {
            "discoverer_max_workers": 3,
            "discoverer_max_depth": 1,
            "discoverer_max_pages": 10,
            "max_workers": 3,
        }
    }
    sites = [
        {"enabled": True, "discoverer": True, "name": "A", "url": "https://a.example/", "category": "WHMCS"},
        {"enabled": True, "discoverer": True, "name": "B", "url": "https://b.example/", "category": "WHMCS"},
        {"enabled": True, "discoverer": True, "name": "C", "url": "https://c.example/", "category": "WHMCS"},
    ]

    rows = _discover_mode(sites, config, DummyHttpClient())

    assert len(rows) == 3
    assert observed_max_workers == [1]
    assert max_active >= 2


def test_discover_mode_runs_even_when_both_outputs_disabled(monkeypatch) -> None:
    monkeypatch.setattr("src.main_scanner._save_tmp", lambda name, payload: None)  # noqa: ARG005

    called_sites: list[str] = []

    class FakeDiscoverer:
        def __init__(self, http_client, max_depth, max_pages, max_workers):  # noqa: ANN001, ARG002
            pass

        def discover(self, site_name: str, base_url: str):  # noqa: ANN001
            called_sites.append(site_name)
            return SimpleNamespace(
                site_name=site_name,
                base_url=base_url,
                visited_urls=[],
                product_candidates=[f"{base_url}product"],
                category_candidates=[f"{base_url}category"],
            )

    monkeypatch.setattr("src.main_scanner.LinkDiscoverer", FakeDiscoverer)

    config = {"scanner": {"discoverer_max_workers": 2, "discoverer_max_depth": 1, "discoverer_max_pages": 10}}
    sites = [
        {
            "enabled": True,
            "discoverer": True,
            "name": "SkipMe",
            "url": "https://skip.example/",
            "category": "WHMCS",
            "product_scanner": False,
            "category_scanner": False,
        },
        {
            "enabled": True,
            "discoverer": True,
            "name": "KeepMe",
            "url": "https://keep.example/",
            "category": "WHMCS",
            "product_scanner": True,
            "category_scanner": False,
        },
    ]

    rows = _discover_mode(sites, config, DummyHttpClient())

    assert set(called_sites) == {"SkipMe", "KeepMe"}
    assert len(rows) == 4
