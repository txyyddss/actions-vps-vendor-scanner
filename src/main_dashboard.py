from __future__ import annotations
"""Generates the static HTML dashboard from the latest product data."""

import json
from pathlib import Path

from src.misc.config_loader import load_config
from src.misc.dashboard_generator import generate_dashboard
from src.misc.logger import setup_logging


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
        generate_dashboard({"generated_at": None, "stats": {}, "products": []}, output_dir="web", dashboard_cfg=dashboard_cfg)
        return
    payload = json.loads(products_path.read_text(encoding="utf-8-sig"))
    generate_dashboard(payload, output_dir="web", dashboard_cfg=dashboard_cfg)


if __name__ == "__main__":
    main()
