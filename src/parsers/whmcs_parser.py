from __future__ import annotations
"""A specialized HTML parser for extracting product details and stock status from WHMCS pages."""

import re
from urllib.parse import parse_qsl, urlparse

from bs4 import BeautifulSoup

from src.parsers.common import ParsedItem, bs4_text, extract_prices

import json
from pathlib import Path

_parser_cfg = {}
try:
    with Path("config/config.json").open("r", encoding="utf-8-sig") as _f:
        _parser_cfg = json.load(_f).get("parsers", {})
except Exception:
    pass

OOS_MARKERS = tuple(_parser_cfg.get("oos_markers", (
    "out of stock",
    "sold out",
    "currently unavailable",
    "is currently unavailable",
    "缺貨中",
    "缺货中",
    "無庫存",
    "无库存",
)))

GENERIC_HEADINGS = {
    "configure",
    "shopping cart",
    "order summary",
    "choose billing cycle",
    "configure server",
}


_text = bs4_text


def _pick_name(soup: BeautifulSoup) -> str:
    """Executes _pick_name logic."""
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


_extract_prices = extract_prices


def _extract_cycles(soup: BeautifulSoup) -> list[str]:
    """Executes _extract_cycles logic."""
    cycle_tokens = ("monthly", "quarterly", "semi-annually", "annually", "biennially", "triennially")
    cycles: list[str] = []
    for node in soup.select("#sectionCycles, .check-cycle, #inputBillingcycle, select[name*=billing], select[name*=cycle]"):
        text = _text(node).lower()
        for token in cycle_tokens:
            if token in text:
                cycles.append(token.title())
    return list(dict.fromkeys(cycles))


def _extract_locations(soup: BeautifulSoup) -> list[str]:
    """Executes _extract_locations logic."""
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
    """Executes _extract_links logic."""
    product_links: list[str] = []
    category_links: list[str] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href"))
        if not href:
            continue
        href_lower = href.lower()
        if "a=add&pid=" in href_lower:
            product_links.append(href)
            continue

        # Check for /store/ in path or inside rp= query parameter
        parsed_href = urlparse(href_lower)
        store_tail = ""
        if "/store/" in parsed_href.path:
            store_tail = parsed_href.path.split("/store/", 1)[-1]
        else:
            # WHMCS uses rp=/store/xxx/yyy query routes
            for key, value in parse_qsl(parsed_href.query, keep_blank_values=True):
                if key.lower() == "rp" and "/store/" in value.lower():
                    store_tail = value.lower().split("/store/", 1)[-1]
                    break

        if store_tail:
            segments = [s for s in store_tail.split("/") if s]
            if len(segments) >= 2:
                product_links.append(href)
            elif len(segments) == 1:
                category_links.append(href)
    return list(dict.fromkeys(product_links)), list(dict.fromkeys(category_links))


def _store_segments_from_url(url: str) -> list[str]:
    """Executes _store_segments_from_url logic."""
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
    """Executes parse_whmcs_page logic."""
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
    # Description: search from most specific to least specific selectors.
    # Avoid .product-info if it was already used for the name (would duplicate).
    desc_selectors = [
        "#productDescription",
        ".product-description",
        ".product-info .description",
        "#frmConfigureProduct",
        ".message-danger",
        ".message",
        ".panel-body",
        ".bordered-section",
        ".product-box",
        ".cart-item",
        ".product-info",
    ]
    description_node = None
    for sel in desc_selectors:
        node = soup.select_one(sel)
        if node:
            text = _text(node)
            if text and len(text) > 10:
                description_node = node
                break
    description_raw = _text(description_node)[:5000] if description_node else ""
    # If description contains the name as prefix, strip it to avoid redundancy.
    if name_raw and description_raw.startswith(name_raw):
        stripped = description_raw[len(name_raw):].lstrip("\n").strip()
        if stripped:
            description_raw = stripped
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
    if soup.select_one("#frmConfigureProduct"):
        evidence.append("has-order-form")
    if soup.select_one("#sectionCycles, .check-cycle, select[name*=cycle]"):
        evidence.append("has-configurable-options")
    if prices:
        evidence.append("has-pricing")
    if product_links:
        evidence.append(f"product-link-count:{len(product_links)}")
    if category_links:
        evidence.append(f"category-link-count:{len(category_links)}")

    # Extract the name from url if there's no name for the category scanner
    if not name_raw and store_segments:
        name_raw = store_segments[-1]

    return ParsedItem(
        platform="WHMCS",
        is_product=is_product,
        is_category=is_category,
        in_stock=in_stock,
        name_raw=name_raw,
        description_raw=description_raw,
        price_raw=", ".join(prices),
        cycles=cycles,
        locations_raw=locations,
        evidence=evidence,
        product_links=product_links,
        category_links=category_links,
    )
