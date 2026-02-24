from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse

from bs4 import BeautifulSoup

from src.parsers.common import ParsedItem

OOS_MARKERS = (
    "out of stock",
    "sold out",
    "currently unavailable",
    "is currently unavailable",
    "缺貨中",
    "缺货中",
    "無庫存",
    "无库存",
)

GENERIC_HEADINGS = {
    "configure",
    "shopping cart",
    "order summary",
    "choose billing cycle",
    "configure server",
}


def _text(node: object) -> str:
    return str(node.get_text(" ", strip=True)) if hasattr(node, "get_text") else ""


def _pick_name(soup: BeautifulSoup) -> str:
    candidates: list[str] = []
    selectors = [
        ".product-title",
        "h1",
        "h2",
        ".panel-title",
        ".product-info .title",
        ".product-info",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = _text(node)
            if not text or len(text) > 140:
                continue
            lowered = text.strip().lower()
            if lowered in GENERIC_HEADINGS:
                continue
            candidates.append(text)

    return candidates[0] if candidates else ""


def _extract_prices(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"(?:[$€£¥]|HK\$)\s?[0-9][0-9,.]*\s?(?:USD|CAD|HKD)?", text)))


def _extract_cycles(soup: BeautifulSoup) -> list[str]:
    cycle_tokens = ("monthly", "quarterly", "semi-annually", "annually", "biennially", "triennially")
    cycles: list[str] = []
    for node in soup.select("#sectionCycles, .check-cycle, #inputBillingcycle, select[name*=billing], select[name*=cycle]"):
        text = _text(node).lower()
        for token in cycle_tokens:
            if token in text:
                cycles.append(token.title())
    return list(dict.fromkeys(cycles))


def _extract_locations(soup: BeautifulSoup) -> list[str]:
    location_hints = ("location", "datacenter", "region", "country", "zone", "节点", "地区", "機房")
    locations: list[str] = []

    for select in soup.select("select"):
        select_text = _text(select).lower()
        name = (select.get("name") or "").lower()
        sid = (select.get("id") or "").lower()
        if not any(hint in select_text or hint in name or hint in sid for hint in location_hints):
            continue
        for option in select.select("option"):
            value = _text(option)
            if value:
                locations.append(value)
    return list(dict.fromkeys(locations))


def _extract_links(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    product_links: list[str] = []
    category_links: list[str] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href"))
        if not href:
            continue
        href_lower = href.lower()
        if "a=add&pid=" in href_lower:
            product_links.append(href)
        elif "/store/" in href_lower:
            # /store/<cat>/<product> usually includes at least 2 path elements.
            path = urlparse(href).path
            store_tail = path.split("/store/")[-1] if "/store/" in path else ""
            slash_count = store_tail.count("/")
            if slash_count >= 1:
                product_links.append(href)
            else:
                category_links.append(href)
    return list(dict.fromkeys(product_links)), list(dict.fromkeys(category_links))


def _store_segments_from_url(url: str) -> list[str]:
    parsed = urlparse(url)
    candidates = [parsed.path]
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() == "rp":
            candidates.append(value)

    for raw in candidates:
        lower = str(raw).lower()
        if "/store/" not in lower:
            continue
        tail = lower.split("/store/", 1)[1]
        segments = [segment for segment in tail.split("/") if segment]
        if segments:
            return segments
    return []


def parse_whmcs_page(html: str, final_url: str) -> ParsedItem:
    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text(" ", strip=True)
    lowered = full_text.lower()
    final_lower = final_url.lower()

    confproduct = "a=confproduct" in final_lower
    has_oos_marker = any(marker in lowered for marker in OOS_MARKERS)
    if has_oos_marker:
        in_stock: bool | None = False
    elif confproduct:
        in_stock = True
    else:
        in_stock = None

    product_links, category_links = _extract_links(soup)
    store_segments = _store_segments_from_url(final_url)
    is_store_product = len(store_segments) >= 2
    is_store_category = len(store_segments) == 1
    is_product = confproduct or is_store_product
    is_category = (is_store_category or bool(category_links or product_links)) and not confproduct and not is_product

    name_raw = _pick_name(soup)
    description_node = soup.select_one(".product-info, #frmConfigureProduct, .message-danger, .message")
    description_raw = _text(description_node)[:5000] if description_node else ""
    prices = _extract_prices(full_text)
    cycles = _extract_cycles(soup)
    locations = _extract_locations(soup)

    evidence: list[str] = []
    if confproduct:
        evidence.append("confproduct-final-url")
    if has_oos_marker:
        evidence.append("oos-marker")
    if "message-danger" in html.lower():
        evidence.append("message-danger")

    return ParsedItem(
        platform="WHMCS",
        is_product=is_product,
        is_category=is_category,
        in_stock=in_stock,
        name_raw=name_raw,
        name_en=name_raw,
        description_raw=description_raw,
        description_en=description_raw,
        price_raw=", ".join(prices),
        cycles=cycles,
        locations_raw=locations,
        locations_en=locations,
        evidence=evidence,
        product_links=product_links,
        category_links=category_links,
    )
