"""A specialized HTML parser for extracting product details and stock status from HostBill pages."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

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
            "currently unavailable",
            "unavailable",
            "no services yet",
        ),
    )
)
NO_SERVICES_MARKER = "no services yet"
ACTIVE_OOS_MARKERS = tuple(marker for marker in OOS_MARKERS if marker.lower() != NO_SERVICES_MARKER)

NON_PRODUCT_REDIRECT_MARKERS = ("/checkdomain/",)


_text = bs4_text


_extract_prices = extract_prices


def _extract_cycles(text: str) -> list[str]:
    """Executes _extract_cycles logic."""
    cycle_tokens = (
        "monthly",
        "quarterly",
        "semi-annually",
        "annually",
        "biennially",
        "triennially",
    )
    cycles = [token.title() for token in cycle_tokens if token in text.lower()]
    return list(dict.fromkeys(cycles))


def _extract_inline_links(html: str) -> list[str]:
    """Extract cart-like URLs from raw HTML/script blobs."""
    pattern = re.compile(
        r"(https?://[^'\"\s<>]+|/index\.php\?/cart/[^'\"\s<>]+|/cart/[^'\"\s<>]+)", re.IGNORECASE
    )
    return list(dict.fromkeys(match.group(1) for match in pattern.finditer(html)))


def _extract_product_links(soup: BeautifulSoup, html: str) -> list[str]:
    """Executes _extract_product_links logic."""
    links: list[str] = []

    # HostBill frequently embeds product IDs inside forms.
    for form in soup.select("form"):
        hidden = {i.get("name"): i.get("value") for i in form.select("input[type=hidden][name]")}
        if hidden.get("action") == "add" and hidden.get("id"):
            links.append(f"/index.php?/cart/&action=add&id={hidden['id']}")

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href", ""))
        lower = href.lower()
        if "action=add&id=" in lower or re.search(r"[?&]id=\d+", lower):
            links.append(href)

    for candidate in _extract_inline_links(html):
        lower = candidate.lower()
        if "action=add&id=" in lower or re.search(r"[?&]id=\d+", lower):
            links.append(candidate)

    return list(dict.fromkeys(links))


def _extract_category_links(soup: BeautifulSoup, html: str) -> list[str]:
    """Executes _extract_category_links logic."""
    links: list[str] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href", ""))
        lower = href.lower()
        if "/cart/" in lower and "action=add&id=" not in lower and "step=3" not in lower:
            links.append(href)
        if "cmd=cart&cat_id=" in lower:
            links.append(href)

    for candidate in _extract_inline_links(html):
        lower = candidate.lower()
        if "/cart/" in lower and "action=add&id=" not in lower and "step=3" not in lower:
            links.append(candidate)
        if "cmd=cart&cat_id=" in lower:
            links.append(candidate)
    return list(dict.fromkeys(links))


def _strip_noscript(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove noscript boilerplate before extracting parser signals."""
    for node in soup.select("noscript"):
        node.decompose()
    return soup


def _hostbill_cart_segments_from_url(final_url: str) -> list[str]:
    """Extract cart-route segments from HostBill pseudo-route URLs."""
    parsed = urlparse(final_url)
    route_source = ""
    if parsed.query.startswith("/"):
        route_source = parsed.query
    elif "/cart/" in parsed.path.lower():
        route_source = parsed.path
    if not route_source:
        return []

    route_source = route_source.split("&", 1)[0]
    cart_marker = "/cart/"
    cart_index = route_source.lower().find(cart_marker)
    if cart_index == -1:
        return []

    route_tail = route_source[cart_index + len(cart_marker) :].strip("/")
    if not route_tail:
        return []
    return [segment for segment in route_tail.split("/") if segment]


def parse_hostbill_page(html: str, final_url: str) -> ParsedItem:
    """Executes parse_hostbill_page logic."""
    soup = _strip_noscript(BeautifulSoup(html, "lxml"))
    cleaned_html = str(soup)
    full_text = soup.get_text(" ", strip=True)
    lowered = full_text.lower()
    final_lower = final_url.lower()

    # Product validity signals for HostBill are multi-source and theme dependent.
    is_non_product_redirect = any(marker in final_lower for marker in NON_PRODUCT_REDIRECT_MARKERS)
    product_links = _extract_product_links(soup, cleaned_html)
    category_links_list = _extract_category_links(soup, cleaned_html)
    prices = _extract_prices(full_text)
    has_order_step = "step=3" in final_lower
    has_add_id = "action=add&id=" in final_lower
    has_oos_marker = any(marker in lowered for marker in ACTIVE_OOS_MARKERS)
    lowered_html = cleaned_html.lower()
    has_js_errors = "var errors" in lowered_html and any(
        marker in lowered_html for marker in ACTIVE_OOS_MARKERS
    )
    disabled_oos_button = soup.select_one("button[disabled]")
    has_disabled_oos_button = bool(
        disabled_oos_button and "out of stock" in _text(disabled_oos_button).lower()
    )
    has_confirmed_add_id = has_add_id and (
        bool(prices)
        or bool(product_links)
        or has_oos_marker
        or has_js_errors
        or has_disabled_oos_button
    )
    has_product_signals = has_order_step or has_confirmed_add_id
    has_category_signals = bool(category_links_list) or bool(product_links)
    has_content_signals = has_order_step or has_category_signals or bool(prices)
    has_blocking_no_services = NO_SERVICES_MARKER in lowered and not has_content_signals
    is_product = (
        has_product_signals and not has_blocking_no_services and not is_non_product_redirect
    )
    is_category = (
        has_category_signals
        and not has_blocking_no_services
        and not is_non_product_redirect
        and not is_product
    )

    if has_blocking_no_services:
        in_stock: bool | None = None
    elif has_oos_marker or has_js_errors or has_disabled_oos_button:
        in_stock = False
    elif is_product:
        in_stock = True
    else:
        in_stock = None

    name_candidates = []
    for selector in ("h1", "h2", ".product-name", ".main-title", ".plan-title", ".producttitle"):
        for node in soup.select(selector):
            text = _text(node)
            if text and len(text) <= 160:
                name_candidates.append(text)
    name_raw = name_candidates[0] if name_candidates else ""
    if not name_raw and is_category:
        cart_segments = _hostbill_cart_segments_from_url(final_url)
        if cart_segments:
            name_raw = cart_segments[-1]

    # Description: search multiple selectors from most specific to least.
    desc_selectors = [
        ".product-description",
        ".plan-description",
        ".plan-body",
        ".plan-features",
        ".bordered-section",
        ".product-box",
        ".cart-item",
        ".content-area",
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
    # Strip name prefix from description if present.
    if name_raw and description_raw.startswith(name_raw):
        stripped = description_raw[len(name_raw) :].lstrip("\n").strip()
        if stripped:
            description_raw = stripped

    locations: list[str] = []
    for node in soup.select("label, strong, .title, .field-name"):
        text = _text(node)
        if any(
            token in text.lower()
            for token in ("location", "region", "zone", "country", "datacenter")
        ):
            sibling_text = _text(node.parent)
            if sibling_text:
                locations.append(sibling_text[:160])
    locations = list(dict.fromkeys(locations))

    evidence: list[str] = []
    if has_oos_marker:
        evidence.append("oos-marker")
    if has_js_errors:
        evidence.append("js-errors-array")
    if has_disabled_oos_button:
        evidence.append("disabled-oos-button")
    if has_blocking_no_services:
        evidence.append("no-services-yet")
    if has_order_step:
        evidence.append("order-step")
    if has_add_id:
        evidence.append("add-id-url")
    if product_links:
        evidence.append(f"product-link-count:{len(product_links)}")
    if category_links_list:
        evidence.append(f"category-link-count:{len(category_links_list)}")
    if prices:
        evidence.append("has-pricing")

    return ParsedItem(
        platform="HostBill",
        is_product=is_product,
        is_category=is_category,
        in_stock=in_stock,
        name_raw=name_raw,
        description_raw=description_raw,
        price_raw=", ".join(prices),
        cycles=_extract_cycles(full_text),
        locations_raw=locations,
        evidence=evidence,
        product_links=product_links,
        category_links=category_links_list,
    )
