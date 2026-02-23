from __future__ import annotations

import json
from pathlib import Path

from src.misc.dashboard_generator import generate_dashboard
from src.misc.logger import setup_logging


def main() -> None:
    setup_logging()
    products_path = Path("data/products.json")
    if not products_path.exists():
        generate_dashboard({"generated_at": None, "stats": {}, "products": []}, output_dir="web")
        return
    payload = json.loads(products_path.read_text(encoding="utf-8-sig"))
    generate_dashboard(payload, output_dir="web")


if __name__ == "__main__":
    main()
