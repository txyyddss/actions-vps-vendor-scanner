"""Site-specific parser and fetcher for the ACCK API vendor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import canonicalize_for_merge, normalize_url
from src.site_specific.api_helpers import build_cycles, parse_json_payload

API_URL = "https://api.acck.io/api/v1/store/GetVpsStore"
SHOP_BASE = "https://acck.io/shop/server"


_parse_json_payload = parse_json_payload
_build_cycles = build_cycles


def scan_acck_api(site: dict[str, Any], http_client: HttpClient) -> list[dict[str, Any]]:
    """Executes scan_acck_api logic."""
    logger = get_logger("acck_api")
    now = datetime.now(timezone.utc).isoformat()
    # We rely on FlareSolverr to survive anti-bot pages wrapping API responses.
    response = http_client.get(API_URL, force_english=False)
    if not response.ok or not response.text:
        logger.warning("acck api fetch failed site=%s error=%s", site["name"], response.error)
        return []

    try:
        payload = _parse_json_payload(response.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("acck api json parse failed: %s", exc)
        return []

    data = payload.get("data", [])
    if not isinstance(data, list):
        return []

    records: list[dict[str, Any]] = []
    for area in data:
        area_id = area.get("id")
        area_name = str(area.get("area_name", "")).strip()
        nodes = area.get("nodes", [])
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            node_id = node.get("id")
            node_name = str(node.get("node_name", "")).strip()
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
                        "canonical_url": canonical_url,
                        "source_url": API_URL,
                        "name_raw": plan_name,
                        "description_raw": description,
                        "in_stock": 1 if stock > 0 else 0,
                        "type": "product",
                        "time_used": response.elapsed_ms,
                        "price_raw": price_raw,
                        "cycles": cycles,
                        "locations_raw": [f"{area_name} - {node_name}"] if area_name else [],
                        "evidence": [f"api-stock:{stock}", "acck-api"],
                        "first_seen_at": now,
                        "last_seen_at": now,
                    }
                )
    return records
