"""A specialized HTML parser for extracting product details and stock status from WHMCS pages."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from bs4 import BeautifulSoup

from src.parsers.common import ParsedItem, bs4_text, extract_prices

_parser_cfg = {}
try:
    with Path("config/config.json").open("r", encoding="utf-8-sig") as _f:
        _parser_cfg = json.load(_f).get("parsers", {})
except Exception:
    pass

OOS_MARKERS = tuple(
    _parser_cfg.get(
        "oos_markers",
        (
            "out of stock",
            "sold out",
            "currently unavailable",
            "is currently unavailable",
            "缺貨中",
            "缺货中",
            "無庫存",
            "无库存",
        ),
    )
)

LANGUAGE_QUERY_KEYS = {"language", "lang", "locale"}
PRODUCT_LIKE_ROUTES = {"confproduct", "store_product", "cart_add"}

GENERIC_HEADINGS = {
    "configure",
    "shopping cart",
    "order summary",
    "choose billing cycle",
    "configure server",
}


_text = bs4_text


def _unique_nodes(soup: BeautifulSoup, selectors: list[str]) -> list:
    """Return unique nodes across selectors in discovery order."""
    seen: set[int] = set()
    nodes: list = []
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            nodes.append(node)
    return nodes


def _texts_from_nodes(nodes: list) -> list[str]:
    """Extract deduplicated text from nodes."""
    seen: set[str] = set()
    texts: list[str] = []
    for node in nodes:
        text = _text(node)
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        texts.append(text)
    return texts


def _has_oos_marker(texts: list[str]) -> bool:
    """Return whether any candidate text contains a configured OOS marker."""
    lowered_texts = [text.lower() for text in texts if text]
    return any(marker in text for marker in OOS_MARKERS for text in lowered_texts)


def _pick_product_title(soup: BeautifulSoup) -> str:
    """Pick a title only from product-specific containers."""
    selectors = [
        ".product-title",
        ".product-info .title",
        "#frmConfigureProduct h1",
        "#frmConfigureProduct h2",
        ".product-details h1",
        ".product-details h2",
        ".product-detail h1",
        ".product-detail h2",
        ".product-info h1",
        ".product-info h2",
    ]
    for node in _unique_nodes(soup, selectors):
        text = _text(node)
        if not text or len(text) > 140:
            continue
        lowered = text.strip().lower()
        if lowered in GENERIC_HEADINGS:
            continue
        return text
    return ""


def classify_whmcs_route(final_url: str) -> str:
    """Classify the final WHMCS route shape used for parser/scanner decisions."""
    parsed = urlparse(final_url)
    query_map: dict[str, str] = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.strip().lower()
        if normalized and normalized not in query_map:
            query_map[normalized] = value

    action = query_map.get("a", "").strip().lower()
    if action == "confproduct":
        return "confproduct"

    store_segments = _store_segments_from_url(final_url)
    if len(store_segments) >= 2:
        return "store_product"
    if len(store_segments) == 1:
        return "store_category"

    if parsed.path.lower().endswith("cart.php"):
        meaningful = {
            key: value for key, value in query_map.items() if key not in LANGUAGE_QUERY_KEYS
        }
        if action == "add" and "pid" in meaningful:
            return "cart_add"
        if not meaningful:
            return "cart_root"

    return "other"


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
    cycle_tokens = (
        "monthly",
        "quarterly",
        "semi-annually",
        "annually",
        "biennially",
        "triennially",
    )
    cycles: list[str] = []
    for node in soup.select(
        "#sectionCycles, .check-cycle, #inputBillingcycle, select[name*=billing], select[name*=cycle]"
    ):
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
    route = classify_whmcs_route(final_url)
    confproduct = route == "confproduct"

    product_links, category_links = _extract_links(soup)
    alert_nodes = _unique_nodes(
        soup, [".message-danger", ".message", ".alert-danger", ".alert", ".errorbox"]
    )
    product_signal_nodes = _unique_nodes(
        soup,
        [
            "#frmConfigureProduct",
            "#productDescription",
            ".product-description",
            ".product-info .description",
            ".product-info",
            ".product-details",
            ".product-detail",
            ".cart-item",
            "#sectionCycles",
            ".check-cycle",
            "#inputBillingcycle",
            "select[name*=billing]",
            "select[name*=cycle]",
        ],
    )
    cart_add_oos_nodes = []
    if route == "cart_add":
        # Some WHMCS templates keep generic OOS pages on cart.php?a=add&pid=...
        cart_add_oos_nodes = _unique_nodes(soup, ["#order-boxes"])

    oos_nodes = alert_nodes
    if route in PRODUCT_LIKE_ROUTES:
        oos_nodes = [*alert_nodes, *product_signal_nodes, *cart_add_oos_nodes]
    has_oos_marker = _has_oos_marker(_texts_from_nodes(oos_nodes))

    name_raw = _pick_name(soup)
    product_title = _pick_product_title(soup)
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
        stripped = description_raw[len(name_raw) :].lstrip("\n").strip()
        if stripped:
            description_raw = stripped
    prices = _extract_prices(full_text)
    product_prices = _extract_prices("\n".join(_texts_from_nodes(product_signal_nodes)))
    cycles = _extract_cycles(soup)
    locations = _extract_locations(soup)

    has_order_form = bool(soup.select_one("#frmConfigureProduct"))
    has_configurable_options = bool(
        soup.select_one(
            "#sectionCycles, .check-cycle, #inputBillingcycle, select[name*=billing], select[name*=cycle]"
        )
    )
    has_product_description = bool(
        soup.select_one(
            "#productDescription, .product-description, .product-info .description, .product-info"
        )
    )
    has_continue_cta = False
    for root in product_signal_nodes:
        for node in root.select("button, input[type=submit], input[type=button], a"):
            label = _text(node) or str(node.get("value", "")).strip()
            if "continue" in label.lower():
                has_continue_cta = True
                break
        if has_continue_cta:
            break

    has_product_info = False
    if route in PRODUCT_LIKE_ROUTES:
        name_signal = bool(
            product_title or (route in {"confproduct", "store_product"} and name_raw)
        )
        has_product_info = any(
            [
                name_signal,
                bool(product_prices),
                has_product_description,
                has_continue_cta,
                has_order_form,
                has_configurable_options,
            ]
        )

    if confproduct:
        in_stock: bool | None = True
    elif route in PRODUCT_LIKE_ROUTES and has_oos_marker:
        in_stock = False
    elif route in PRODUCT_LIKE_ROUTES and has_product_info:
        in_stock = True
    else:
        in_stock = None

    is_product = route in {"confproduct", "store_product"} or (
        route == "cart_add" and (has_product_info or has_oos_marker)
    )
    is_category = route == "store_category" or (
        route in {"cart_root", "other"} and bool(category_links or product_links)
    )

    evidence: list[str] = []
    if confproduct:
        evidence.append("confproduct-final-url")
    if has_oos_marker:
        evidence.append("oos-marker")
    if "message-danger" in html.lower():
        evidence.append("message-danger")
    if has_order_form:
        evidence.append("has-order-form")
    if has_configurable_options:
        evidence.append("has-configurable-options")
    if has_product_info:
        evidence.append("has-product-info")
    if prices:
        evidence.append("has-pricing")
    if product_links:
        evidence.append(f"product-link-count:{len(product_links)}")
    if category_links:
        evidence.append(f"category-link-count:{len(category_links)}")

    # Extract the name from url if there's no name for the category scanner
    store_segments = _store_segments_from_url(final_url)
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
