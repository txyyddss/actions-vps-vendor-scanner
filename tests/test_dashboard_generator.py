from __future__ import annotations

import json
from pathlib import Path

from src.misc.dashboard_generator import generate_dashboard


def _extract_embedded_data(index_html: str) -> dict[str, object]:
    prefix = "window.__DASHBOARD_DATA__ = "
    start = index_html.index(prefix) + len(prefix)
    end = index_html.index(";</script>", start)
    return json.loads(index_html[start:end])


def test_dashboard_assets_match_generator_template(tmp_path) -> None:
    payload = {
        "generated_at": "2026-02-28T00:00:00+00:00",
        "stats": {
            "total_products": 1,
            "in_stock": 1,
            "out_of_stock": 0,
            "unknown": 0,
        },
        "sites": [
            {
                "site": "Vendor A",
                "platform": "WHMCS",
                "products": [
                    {
                        "canonical_url": "https://example.com/product",
                        "name_raw": "Plan A",
                        "in_stock": 1,
                    }
                ],
                "categories": [],
            }
        ],
    }

    generate_dashboard(payload, output_dir=str(tmp_path), dashboard_cfg={"title": "Test"})

    generated_app = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")
    checked_in_app = Path("web/assets/app.js").read_text(encoding="utf-8")
    embedded_data = _extract_embedded_data((tmp_path / "index.html").read_text(encoding="utf-8"))

    assert "stock_status" not in generated_app
    assert "r.in_stock" in generated_app
    assert generated_app == checked_in_app
    assert embedded_data["products"][0]["site"] == "Vendor A"
    assert embedded_data["products"][0]["platform"] == "WHMCS"
