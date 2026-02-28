"""Handles loading and validating JSON configuration files."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

LEGACY_KEY_MAP = {
    "special crawler": "special_crawler",
    "product scanner": "product_scanner",
    "category scanner": "category_scanner",
}

_CONFIG_CACHE: dict[Path, dict[str, Any]] = {}


def load_json(path: str | Path) -> dict[str, Any]:
    """Executes load_json logic."""
    with Path(path).open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def dump_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Executes dump_json logic."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_config(config_path: str = "config/config.json") -> dict[str, Any]:
    """Load the project config file without caching."""
    return load_json(config_path)


def load_cached_config(config_path: str | Path = "config/config.json") -> dict[str, Any]:
    """Load and cache a config payload for repeated read-only access."""
    cache_key = Path(config_path)
    cached = _CONFIG_CACHE.get(cache_key)
    if cached is None:
        cached = load_json(cache_key)
        _CONFIG_CACHE[cache_key] = cached
    return cached


def load_cached_config_section(
    section: str,
    default: Mapping[str, Any] | None = None,
    config_path: str | Path = "config/config.json",
) -> dict[str, Any]:
    """Return one config section as a plain dict."""
    config = load_cached_config(config_path)
    value = config.get(section)
    if isinstance(value, dict):
        return dict(value)
    return dict(default or {})


def reset_cached_config(config_path: str | Path | None = None) -> None:
    """Clear cached config values so future reads see updated on-disk data."""
    if config_path is None:
        _CONFIG_CACHE.clear()
        return
    _CONFIG_CACHE.pop(Path(config_path), None)


def coerce_positive_int(
    value: Any,
    default: int,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    """Coerce a value to a bounded positive integer."""
    floor = max(1, int(minimum))
    fallback = max(floor, int(default))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback

    if parsed < floor:
        parsed = floor
    if maximum is not None:
        parsed = min(parsed, int(maximum))
    return parsed


def config_string_set(
    section: str,
    key: str,
    default: Iterable[str],
    config_path: str | Path = "config/config.json",
) -> set[str]:
    """Load a lowercase string set from config with a fallback default."""
    configured = load_cached_config_section(section, config_path=config_path).get(key)
    if isinstance(configured, (list, tuple, set)):
        values = {str(item).lower() for item in configured if str(item).strip()}
        if values:
            return values
    return {str(item).lower() for item in default if str(item).strip()}


def config_string_tuple(
    section: str,
    key: str,
    default: Iterable[str],
    config_path: str | Path = "config/config.json",
) -> tuple[str, ...]:
    """Load a lowercase string tuple from config with a fallback default."""
    configured = load_cached_config_section(section, config_path=config_path).get(key)
    if isinstance(configured, (list, tuple, set)):
        values = tuple(str(item).lower() for item in configured if str(item).strip())
        if values:
            return values
    return tuple(str(item).lower() for item in default if str(item).strip())


def normalize_site_entry(site: dict[str, Any]) -> dict[str, Any]:
    """Executes normalize_site_entry logic."""
    from src.misc.url_normalizer import normalize_url

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
