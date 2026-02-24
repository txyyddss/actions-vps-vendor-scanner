from __future__ import annotations
"""Handles loading and validating JSON configuration files."""

import json
from pathlib import Path
from typing import Any

from src.misc.url_normalizer import normalize_url

LEGACY_KEY_MAP = {
    "special crawler": "special_crawler",
    "product scanner": "product_scanner",
    "category scanner": "category_scanner",
}


def load_json(path: str | Path) -> dict[str, Any]:
    """Executes load_json logic."""
    with Path(path).open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def dump_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Executes dump_json logic."""
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_config(config_path: str = "config/config.json") -> dict[str, Any]:
    """Executes load_config logic."""
    return load_json(config_path)


def normalize_site_entry(site: dict[str, Any]) -> dict[str, Any]:
    """Executes normalize_site_entry logic."""
    out = dict(site)
    for legacy, canonical in LEGACY_KEY_MAP.items():
        if legacy in out and canonical not in out:
            out[canonical] = out.pop(legacy)

    out.setdefault("enabled", True)
    out.setdefault("discoverer", True)
    out.setdefault("category", "")
    out.setdefault("special_crawler", "")
    out.setdefault("product_scanner", True)
    out.setdefault("category_scanner", True)
    out.setdefault("scan_bounds", {})
    out["url"] = normalize_url(str(out.get("url", "")), force_english=False)
    return out


def load_sites(config_path: str = "config/sites.json") -> list[dict[str, Any]]:
    """Executes load_sites logic."""
    payload = load_json(config_path)
    sites = payload.get("sites", {}).get("site", [])
    return [normalize_site_entry(site) for site in sites if site]
