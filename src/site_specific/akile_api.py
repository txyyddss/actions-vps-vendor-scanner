from __future__ import annotations
"""Site-specific parser and fetcher for the Akile API vendor."""

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import canonicalize_for_merge, normalize_url

API_URL = "https://api.akile.io/api/v1/store/GetVpsStoreV3"
SHOP_BASE = "https://akile.io/shop/server"


def _parse_json_payload(raw_text: str) -> dict[str, Any]:
    """Executes _parse_json_payload logic."""
    text = raw_text.strip()
    if text.startswith("<"):
        match = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1)
        text = text.replace("&quot;", '"').replace("&amp;", "&")
    return json.loads(text)


def _build_cycles(price_datas: Any) -> tuple[list[str], str]:
    """Executes _build_cycles logic."""
    if not isinstance(price_datas, dict):
        return [], ""
    cycles: list[str] = []
    parts: list[str] = []
    for key, value in price_datas.items():
        cycle_name = str(key).replace("_", " ").title()
        cycles.append(cycle_name)
        parts.append(f"{cycle_name}: {value}")
    return cycles, "; ".join(parts)


def scan_akile_api(site: dict[str, Any], http_client: HttpClient) -> list[dict[str, Any]]:
    """Executes scan_akile_api logic."""
    logger = get_logger("akile_api")
    now = datetime.now(timezone.utc).isoformat()
    # Keep browser fallback enabled to survive anti-bot pages wrapping API responses.
    response = http_client.get(API_URL, force_english=False, allow_browser_fallback=True)
    if not response.ok or not response.text:
        logger.warning("akile api fetch failed site=%s error=%s", site["name"], response.error)
        return []

    try:
        payload = _parse_json_payload(response.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("akile api json parse failed: %s", exc)
        return []

    data = payload.get("data", {})
    areas = data.get("areas", []) if isinstance(data, dict) else []
    if not isinstance(areas, list):
        return []

    records: list[dict[str, Any]] = []
    for area in areas:
        area_id = area.get("id")
        area_name = str(area.get("area_name", "")).strip()
        nodes = area.get("nodes", [])
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            node_id = node.get("id")
            node_name = str(node.get("group_name", "")).strip()
            plans = node.get("plans", [])
            if not isinstance(plans, list):
                continue
            for plan in plans:
                plan_id = plan.get("id")
                stock = int(plan.get("stock", 0) or 0)
                cycles, price_raw = _build_cycles(plan.get("price_datas"))
                plan_name = str(plan.get("plan_name", "")).strip()
                description = str(node.get("detail", "")).strip()
                product_type = "traffic" if str(plan.get("flow", "")).strip() else "bandwidth"
                url = normalize_url(
                    f"{SHOP_BASE}?type={product_type}&areaId={area_id}&nodeId={node_id}&planId={plan_id}",
                    force_english=False,
                )
                canonical_url = canonicalize_for_merge(url)

                records.append(
                    {
                        "site": site["name"],
                        "platform": "SPECIAL",
                        "scan_type": "product_scanner",
                        "source_priority": "product_scanner",
                        "canonical_url": canonical_url,
                        "source_url": API_URL,
                        "stock_status": "in_stock" if stock > 0 else "out_of_stock",
                        "name_raw": plan_name,
                        "name_en": plan_name,
                        "description_raw": description,
                        "description_en": description,
                        "cycles": cycles,
                        "locations_raw": [area_name, node_name],
                        "locations_en": [area_name, node_name],
                        "price_raw": price_raw,
                        "evidence": [f"api-stock:{stock}", "akile-api"],
                        "first_seen_at": now,
                        "last_seen_at": now,
                    }
                )
    return records
