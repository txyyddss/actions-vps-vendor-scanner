from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

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
        self.calls: list[tuple[str, bool]] = []
        self.payload_by_url = payload_by_url or {}

    def get(self, url: str, force_english: bool = True):  # noqa: ANN001
        self.calls.append((url, force_english))
        return SimpleNamespace(
            ok=True,
            requested_url=url,
            final_url=url,
            status_code=200,
            text=self.payload_by_url.get(url, "<html></html>"),
            headers={},
            tier="direct",
            elapsed_ms=10,
            error=None,
        )


def _fixture(name: str) -> str:
    return Path(f"tests/fixtures/{name}").read_text(encoding="utf-8")


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


def test_discoverer_uses_http_client() -> None:
    fake = FakeHttpClient()
    discoverer = LinkDiscoverer(http_client=fake, max_depth=0, max_pages=1, max_workers=1)
    discoverer.discover(site_name="Example", base_url="https://example.com/")

    assert fake.calls


def test_whmcs_and_hostbill_scanners_use_http_client(tmp_path) -> None:
    fake = FakeHttpClient()
    state_store = StateStore(tmp_path / "state.json")
    config = _scanner_config()

    scan_whmcs_gids(_site("W", "https://example.com/"), config, fake, state_store)
    scan_whmcs_pids(_site("W", "https://example.com/"), config, fake, state_store)
    scan_hostbill_catids(_site("H", "https://example.com/"), config, fake, state_store)
    scan_hostbill_pids(_site("H", "https://example.com/"), config, fake, state_store)

    assert fake.calls


@pytest.mark.parametrize(
    ("executor_target", "scanner"),
    [
        ("src.hidden_scanner.whmcs.gid_scanner.ThreadPoolExecutor", scan_whmcs_gids),
        ("src.hidden_scanner.whmcs.pid_scanner.ThreadPoolExecutor", scan_whmcs_pids),
        ("src.hidden_scanner.hostbill.catid_scanner.ThreadPoolExecutor", scan_hostbill_catids),
        ("src.hidden_scanner.hostbill.pid_scanner.ThreadPoolExecutor", scan_hostbill_pids),
    ],
)
def test_hidden_scanners_force_single_worker_per_site(
    tmp_path, monkeypatch, executor_target: str, scanner
) -> None:
    observed_max_workers: list[int | None] = []

    class CapturingExecutor(RealThreadPoolExecutor):
        def __init__(self, max_workers=None, *args, **kwargs):  # noqa: ANN001
            observed_max_workers.append(max_workers)
            super().__init__(max_workers=max_workers, *args, **kwargs)

    monkeypatch.setattr(executor_target, CapturingExecutor)

    fake = FakeHttpClient()
    state_store = StateStore(tmp_path / "state.json")
    config = _scanner_config()
    config["scanner"]["max_workers"] = 12

    scanner(_site("SingleWorker", "https://example.com/"), config, fake, state_store)
    assert observed_max_workers == [1]


def test_special_api_scanners_use_http_client() -> None:
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
                        "plans": [
                            {
                                "id": 78,
                                "stock": 1,
                                "plan_name": "P1",
                                "price_datas": {"monthly": 5.0},
                                "flow": 1,
                            }
                        ],
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
                            "plans": [
                                {
                                    "id": 934,
                                    "stock": 2,
                                    "plan_name": "P2",
                                    "price_datas": {"monthly": 6.0},
                                    "flow": 1,
                                }
                            ],
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

    assert (ACCK_API_URL, False) in fake.calls
    assert (AKILE_API_URL, False) in fake.calls


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
            "stop_inactive_streak_product": 8,
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
    first_url, _ = fake.calls[0]
    assert "pid=110" in first_url


def test_whmcs_scanners_use_split_inactive_streak_limits(tmp_path) -> None:
    state_store = StateStore(tmp_path / "state.json")
    config = {
        "scanner": {
            "max_workers": 1,
            "scan_batch_size": 1,
            "initial_scan_floor": 0,
            "stop_tail_window": 200,
            "stop_inactive_streak_category": 20,
            "stop_inactive_streak_product": 60,
            "default_scan_bounds": {
                "whmcs_gid_max": 300,
                "whmcs_pid_max": 300,
                "hostbill_catid_max": 0,
                "hostbill_pid_max": 0,
            },
        }
    }
    site = _site("SplitWHMCS", "https://example.com/")
    site["scan_bounds"]["whmcs_gid_max"] = 300
    site["scan_bounds"]["whmcs_pid_max"] = 300

    category_client = FakeHttpClient()
    scan_whmcs_gids(site, config, category_client, state_store)
    assert len(category_client.calls) == 20

    product_client = FakeHttpClient()
    scan_whmcs_pids(site, config, product_client, state_store)
    assert len(product_client.calls) == 60


def test_whmcs_pid_scanner_ignores_oos_category_redirects_for_stop_logic(tmp_path) -> None:
    html = """
    <html><body>
      <div class="message message-danger">Out of Stock We are currently out of stock on this item.</div>
      <a href="/store/vps/basic">Basic</a>
    </body></html>
    """

    class RedirectingCategoryClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url="https://example.com/store/vps",
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = RedirectingCategoryClient()
    state_store = StateStore(tmp_path / "state.json")
    config = {
        "scanner": {
            "max_workers": 1,
            "scan_batch_size": 1,
            "initial_scan_floor": 20,
            "stop_tail_window": 20,
            "stop_inactive_streak_product": 20,
            "default_scan_bounds": {
                "whmcs_gid_max": 0,
                "whmcs_pid_max": 200,
                "hostbill_catid_max": 0,
                "hostbill_pid_max": 0,
            },
        }
    }
    site = _site("RedirectedWHMCS", "https://example.com/")
    site["scan_bounds"]["whmcs_pid_max"] = 200

    records = scan_whmcs_pids(site, config, fake, state_store)

    assert records == []
    assert len(fake.calls) == 21


def test_whmcs_pid_scanner_accepts_confproduct_as_in_stock(tmp_path) -> None:
    html = """
    <html><body>
      <div id="frmConfigureProduct">
        <h2 class="product-title">Fast VPS</h2>
        <div id="sectionCycles">Monthly $10.00 USD</div>
        <button type="submit">Continue</button>
      </div>
    </body></html>
    """

    class ConfproductClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url="https://example.com/cart.php?a=confproduct&i=0",
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = ConfproductClient()
    state_store = StateStore(tmp_path / "state.json")

    records = scan_whmcs_pids(
        _site("ConfproductWHMCS", "https://example.com/"), _scanner_config(), fake, state_store
    )

    assert len(records) == 1
    assert records[0]["in_stock"] == 1
    assert "confproduct-final-url" in records[0]["evidence"]
    assert "has-product-info" in records[0]["evidence"]


def test_whmcs_pid_scanner_accepts_oos_store_product(tmp_path) -> None:
    html = """
    <html><body>
      <div class="message message-danger">Out of Stock We are currently out of stock on this item.</div>
      <h2>Outage Plan</h2>
    </body></html>
    """

    class OosProductClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url="https://example.com/store/vps/outage-plan",
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = OosProductClient()
    state_store = StateStore(tmp_path / "state.json")

    records = scan_whmcs_pids(
        _site("OOSWHMCS", "https://example.com/"), _scanner_config(), fake, state_store
    )

    assert len(records) == 1
    assert records[0]["in_stock"] == 0
    assert "oos-marker" in records[0]["evidence"]


def test_whmcs_pid_scanner_keeps_distinct_cart_add_oos_products(tmp_path) -> None:
    html = """
    <html><body>
      <div id="order-boxes">
        <div class="header-lined"><h1>Out of Stock</h1></div>
        <p>We are currently out of stock on this item so orders for it have been suspended until more stock is available.</p>
      </div>
    </body></html>
    """

    class CartAddOosClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = CartAddOosClient()
    state_store = StateStore(tmp_path / "state.json")
    config = _scanner_config()
    config["scanner"]["default_scan_bounds"]["whmcs_pid_max"] = 1
    site = _site("CartAddOOSWHMCS", "https://example.com/")
    site["scan_bounds"]["whmcs_pid_max"] = 1

    records = scan_whmcs_pids(site, config, fake, state_store)

    assert len(records) == 2
    assert [record["pid"] for record in records] == [0, 1]
    assert all(record["in_stock"] == 0 for record in records)
    assert len({record["canonical_url"] for record in records}) == 2


def test_whmcs_pid_scanner_rejects_cart_root_redirect(tmp_path) -> None:
    html = """
    <html><body>
      <h2 class="product-title">Fast VPS</h2>
      <div>$10.00 USD</div>
      <button>Continue</button>
    </body></html>
    """

    class CartRootClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url="https://example.com/cart.php",
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = CartRootClient()
    state_store = StateStore(tmp_path / "state.json")

    records = scan_whmcs_pids(
        _site("CartRootWHMCS", "https://example.com/"), _scanner_config(), fake, state_store
    )

    assert records == []


def test_whmcs_pid_scanner_rejects_category_listing_redirect(tmp_path) -> None:
    html = """
    <html><body>
      <h1>Shared VPS</h1>
      <div class="product-box">
        <div>$10.00 USD monthly</div>
        <div>0 available</div>
        <a href="/store/shared/plan-a">Order Now</a>
      </div>
    </body></html>
    """

    class CategoryListingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url="https://example.com/store/shared",
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = CategoryListingClient()
    state_store = StateStore(tmp_path / "state.json")

    records = scan_whmcs_pids(
        _site("CategoryWHMCS", "https://example.com/"), _scanner_config(), fake, state_store
    )

    assert records == []


def test_whmcs_pid_scanner_rejects_cart_add_listing_page(tmp_path) -> None:
    html = """
    <html><body>
      <div class="product-box">
        <h2>Plan A</h2>
        <div>$10.00 USD monthly</div>
        <div>0 available</div>
        <a href="/store/shared/plan-a">Order Now</a>
      </div>
    </body></html>
    """

    class CartAddListingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = CartAddListingClient()
    state_store = StateStore(tmp_path / "state.json")

    records = scan_whmcs_pids(
        _site("CartAddListingWHMCS", "https://example.com/"), _scanner_config(), fake, state_store
    )

    assert records == []


def test_whmcs_pid_scanner_deduplicates_confproduct_content(tmp_path) -> None:
    html = """
    <html><body>
      <div id="frmConfigureProduct">
        <h2 class="product-title">Fast VPS</h2>
        <div id="sectionCycles">Monthly $10.00 USD</div>
        <button type="submit">Continue</button>
      </div>
    </body></html>
    """

    class DuplicateConfproductClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            conf_index = len(self.calls) - 1
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url=f"https://example.com/cart.php?a=confproduct&i={conf_index}",
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = DuplicateConfproductClient()
    state_store = StateStore(tmp_path / "state.json")
    config = _scanner_config()
    config["scanner"]["default_scan_bounds"]["whmcs_pid_max"] = 1
    site = _site("DuplicateWHMCS", "https://example.com/")
    site["scan_bounds"]["whmcs_pid_max"] = 1

    records = scan_whmcs_pids(site, config, fake, state_store)

    assert len(records) == 1
    assert records[0]["pid"] == 0
    assert len(fake.calls) == 2


def test_hostbill_catid_scanner_stops_after_navigation_only_no_services_streak(
    tmp_path, caplog
) -> None:
    fallback_html = _fixture("hostbill_category_navigation_only_no_services.html")

    class HostBillCatidFallbackClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                text=fallback_html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    caplog.set_level(logging.INFO, logger="hostbill_catid_scanner")
    fake = HostBillCatidFallbackClient()
    state_store = StateStore(tmp_path / "state.json")
    config = {
        "scanner": {
            "max_workers": 1,
            "scan_batch_size": 1,
            "initial_scan_floor": 0,
            "stop_tail_window": 20,
            "stop_inactive_streak_category": 8,
            "default_scan_bounds": {
                "whmcs_gid_max": 0,
                "whmcs_pid_max": 0,
                "hostbill_catid_max": 50,
                "hostbill_pid_max": 0,
            },
        }
    }
    site = _site("HostBillCatFallback", "https://example.com/")
    site["scan_bounds"]["hostbill_catid_max"] = 50

    records = scan_hostbill_catids(site, config, fake, state_store)

    assert records == []
    assert len(fake.calls) == 8
    assert any(
        "hostbill catid scan site=HostBillCatFallback" in record.getMessage()
        and "stop=inactive-streak=8" in record.getMessage()
        for record in caplog.records
    )


def test_hostbill_catid_scanner_keeps_real_categories_and_logs_category_count(
    tmp_path, caplog
) -> None:
    valid_html = _fixture("hostbill_category_generic_with_products.html")
    fallback_html = _fixture("hostbill_category_navigation_only_no_services.html")

    class HostBillCatidClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            cat_id = int(url.rsplit("=", 1)[-1])
            html = valid_html if cat_id == 0 else fallback_html
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    caplog.set_level(logging.INFO, logger="hostbill_catid_scanner")
    fake = HostBillCatidClient()
    state_store = StateStore(tmp_path / "state.json")
    config = {
        "scanner": {
            "max_workers": 1,
            "scan_batch_size": 1,
            "initial_scan_floor": 0,
            "stop_tail_window": 20,
            "stop_inactive_streak_category": 20,
            "default_scan_bounds": {
                "whmcs_gid_max": 0,
                "whmcs_pid_max": 0,
                "hostbill_catid_max": 50,
                "hostbill_pid_max": 0,
            },
        }
    }
    site = _site("HostBillCatProgress", "https://example.com/")
    site["scan_bounds"]["hostbill_catid_max"] = 50

    records = scan_hostbill_catids(site, config, fake, state_store)
    category_rows = [record for record in records if record["type"] == "category"]
    product_rows = [record for record in records if record["type"] == "product"]

    assert [record["cat_id"] for record in category_rows] == [0]
    assert [record["cat_id"] for record in product_rows] == [0, 0]
    assert len(fake.calls) == 21
    assert any(
        "hostbill catid progress site=HostBillCatProgress" in record.getMessage()
        and "discovered=1 rows=3" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        "hostbill catid scan site=HostBillCatProgress" in record.getMessage()
        and "stop=inactive-streak=20" in record.getMessage()
        for record in caplog.records
    )


def test_hostbill_pid_scanner_stops_after_invalid_add_id_listing_streak(tmp_path) -> None:
    oos_html = """
    <html><body>
      <script>
      var errors = ["Special plan is currently out of stock"];
      </script>
      <button type="submit" class="btn disabled" disabled="disabled">Out of stock!</button>
      <h2>Special Offer Plan</h2>
    </body></html>
    """
    invalid_listing_html = """
    <html><body>
      <script>var errors = [];</script>
      <h2>Browse Products and Services</h2>
      <a href="/index.php?/cart/special-offer/">Special Offer</a>
      <div>No services yet</div>
    </body></html>
    """

    class HostBillPidClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, force_english: bool = True):  # noqa: ANN001
            self.calls.append((url, force_english))
            pid = int(url.rsplit("=", 1)[-1])
            html = oos_html if pid == 0 else invalid_listing_html
            return SimpleNamespace(
                ok=True,
                requested_url=url,
                final_url=url,
                status_code=200,
                text=html,
                headers={},
                tier="direct",
                elapsed_ms=10,
                error=None,
            )

    fake = HostBillPidClient()
    state_store = StateStore(tmp_path / "state.json")
    config = {
        "scanner": {
            "max_workers": 1,
            "scan_batch_size": 1,
            "initial_scan_floor": 0,
            "stop_tail_window": 20,
            "stop_inactive_streak_product": 8,
            "default_scan_bounds": {
                "whmcs_gid_max": 0,
                "whmcs_pid_max": 0,
                "hostbill_catid_max": 0,
                "hostbill_pid_max": 50,
            },
        }
    }
    site = _site("HostBillStop", "https://example.com/")
    site["scan_bounds"]["hostbill_pid_max"] = 50

    records = scan_hostbill_pids(site, config, fake, state_store)

    assert len(records) == 1
    assert records[0]["pid"] == 0
    assert len(fake.calls) == 9
