"""Generates the static HTML dashboard from the latest product data."""

from __future__ import annotations

import json
from pathlib import Path

from src.misc.config_loader import load_config
from src.misc.dashboard_generator import generate_dashboard
from src.misc.logger import setup_logging
from src.others.data_merge import _group_by_site, load_products


def main() -> None:
    """Executes main logic."""
    config = load_config("config/config.json")
    setup_logging(
        level=str(config.get("logging", {}).get("level", "INFO")),
        json_logs=bool(config.get("logging", {}).get("json_logs", False)),
    )
    dashboard_cfg = config.get("dashboard", {})
    products_path = Path("data/products.json")
    if not products_path.exists():
        generate_dashboard(
            {"generated_at": None, "stats": {}, "sites": []},
            output_dir="web",
            dashboard_cfg=dashboard_cfg,
        )
        return
    # Read raw payload for metadata (generated_at, stats), then build site-grouped data
    raw = json.loads(products_path.read_text(encoding="utf-8-sig"))
    # If already site-grouped, pass through; otherwise rebuild from flat list
    if "sites" in raw:
        generate_dashboard(raw, output_dir="web", dashboard_cfg=dashboard_cfg)
    else:
        products = load_products("data/products.json")
        sites = _group_by_site(products)
        payload = {
            "generated_at": raw.get("generated_at"),
            "stats": raw.get("stats", {}),
            "sites": sites,
        }
        generate_dashboard(payload, output_dir="web", dashboard_cfg=dashboard_cfg)


if __name__ == "__main__":
    main()
