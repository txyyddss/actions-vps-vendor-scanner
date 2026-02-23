from __future__ import annotations

import json
from types import SimpleNamespace

from src.discoverer.link_discoverer import LinkDiscoverer
from src.hidden_scanner.hostbill.catid_scanner import scan_hostbill_catids
from src.hidden_scanner.hostbill.pid_scanner import scan_hostbill_pids
from src.hidden_scanner.whmcs.gid_scanner import scan_whmcs_gids
from src.hidden_scanner.whmcs.pid_scanner import scan_whmcs_pids
from src.others.state_store import StateStore
from src.site_specific.acck_api import API_URL as ACCK_API_URL
from src.site_specific.acck_api import scan_acck_api
from src.site_specific.akile_api import API_URL as AKILE_API_URL
from src.site_specific.akile_api import scan_akile_api


class FakeHttpClient:
    def __init__(self, payload_by_url: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, bool, bool]] = []
        self.payload_by_url = payload_by_url or {}

    def get(self, url: str, force_english: bool = True, allow_browser_fallback: bool = True):  # noqa: ANN001
        self.calls.append((url, force_english, allow_browser_fallback))
        return SimpleNamespace(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=200,
            text=self.payload_by_url.get(url, "<html></html>"),
            headers={},
            tier="direct",
            error=None,
        )


def _scanner_config() -> dict:
    return {
        "scanner": {
            "max_workers": 1,
            "initial_scan_floor": 0,
            "stop_tail_window": 0,
            "default_scan_bounds": {
                "whmcs_gid_max": 0,
                "whmcs_pid_max": 0,
                "hostbill_catid_max": 0,
                "hostbill_pid_max": 0,
            },
        }
    }


def _site(name: str, url: str) -> dict:
    return {
        "name": name,
        "url": url,
        "scan_bounds": {
            "whmcs_gid_max": 0,
            "whmcs_pid_max": 0,
            "hostbill_catid_max": 0,
            "hostbill_pid_max": 0,
        },
    }


def test_discoverer_uses_browser_fallback() -> None:
    fake = FakeHttpClient()
    discoverer = LinkDiscoverer(http_client=fake, max_depth=0, max_pages=1, max_workers=1)
    discoverer.discover(site_name="Example", base_url="https://example.com/")

    assert fake.calls
    assert all(call[2] is True for call in fake.calls)


def test_whmcs_and_hostbill_scanners_use_browser_fallback(tmp_path) -> None:
    fake = FakeHttpClient()
    state_store = StateStore(tmp_path / "state.json")
    config = _scanner_config()

    scan_whmcs_gids(_site("W", "https://example.com/"), config, fake, state_store)
    scan_whmcs_pids(_site("W", "https://example.com/"), config, fake, state_store)
    scan_hostbill_catids(_site("H", "https://example.com/"), config, fake, state_store)
    scan_hostbill_pids(_site("H", "https://example.com/"), config, fake, state_store)

    assert fake.calls
    assert all(call[2] is True for call in fake.calls)


def test_special_api_scanners_use_browser_fallback() -> None:
    acck_payload = {
        "data": [
            {
                "id": 1,
                "area_name": "HK",
                "nodes": [
                    {
                        "id": 9,
                        "node_name": "Node 9",
                        "detail": "detail",
                        "plans": [{"id": 78, "stock": 1, "plan_name": "P1", "price_datas": {"monthly": 5.0}, "flow": 1}],
                    }
                ],
            }
        ]
    }
    akile_payload = {
        "data": {
            "areas": [
                {
                    "id": 2,
                    "area_name": "JP",
                    "nodes": [
                        {
                            "id": 23,
                            "group_name": "Node 23",
                            "detail": "detail",
                            "plans": [{"id": 934, "stock": 2, "plan_name": "P2", "price_datas": {"monthly": 6.0}, "flow": 1}],
                        }
                    ],
                }
            ]
        }
    }
    fake = FakeHttpClient(
        {
            ACCK_API_URL: json.dumps(acck_payload),
            AKILE_API_URL: json.dumps(akile_payload),
        }
    )
    site = {"name": "S"}
    assert scan_acck_api(site, fake)
    assert scan_akile_api(site, fake)

    assert (ACCK_API_URL, False, True) in fake.calls
    assert (AKILE_API_URL, False, True) in fake.calls


def test_whmcs_pid_scanner_resumes_from_highwater_tail(tmp_path) -> None:
    fake = FakeHttpClient()
    state_store = StateStore(tmp_path / "state.json")
    state_store.update_site_state("ResumeWHMCS", {"whmcs_pid_highwater": 120})

    config = {
        "scanner": {
            "max_workers": 1,
            "scan_batch_size": 1,
            "initial_scan_floor": 0,
            "stop_tail_window": 10,
            "stop_inactive_streak": 8,
            "default_scan_bounds": {
                "whmcs_gid_max": 0,
                "whmcs_pid_max": 300,
                "hostbill_catid_max": 0,
                "hostbill_pid_max": 0,
            },
        }
    }
    site = _site("ResumeWHMCS", "https://example.com/")
    site["scan_bounds"]["whmcs_pid_max"] = 300

    scan_whmcs_pids(site, config, fake, state_store)
    assert fake.calls
    first_url, _, _ = fake.calls[0]
    assert "pid=110" in first_url
