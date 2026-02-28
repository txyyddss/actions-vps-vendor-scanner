"""Normalizes, classifies, and filters URLs to ensure consistent merging and processing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

_url_cfg = {}
try:
    with Path("config/config.json").open("r", encoding="utf-8-sig") as _f:
        _url_cfg = json.load(_f).get("url_normalizer", {})
except Exception:
    pass

INVALID_PATH_PATTERNS = tuple(
    _url_cfg.get(
        "invalid_path_patterns",
        (
            "contact",
            "contact.php",
            "announcements",
            "announcement",
            "knowledgebase",
            "submitticket",
            "supporttickets",
            "supporttickets.php",
            "clientarea",
            "login",
            "password",
            "pwreset",
            "forgot",
            "register",
            "affiliates",
        ),
    )
)

INVALID_EXTENSIONS = set(
    _url_cfg.get(
        "invalid_extensions",
        [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".svg",
            ".ico",
            ".css",
            ".js",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
        ],
    )
)

VOLATILE_QUERY_KEYS = set(
    _url_cfg.get(
        "volatile_query_keys",
        [
            "sid",
            "session",
            "phpsessid",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
        ],
    )
)

ENGLISH_LANGUAGE_TAGS = set(
    _url_cfg.get("english_language_tags", ["en", "en-us", "en_us", "en-gb", "en_gb", "english"])
)

LANGUAGE_QUERY_KEYS = set(_url_cfg.get("language_query_keys", ["language", "lang", "locale"]))
ROUTE_QUERY_KEYS = set(_url_cfg.get("route_query_keys", ["rp"]))


@dataclass(slots=True)
class UrlClassification:
    """Represents UrlClassification."""

    url: str
    is_invalid_product_url: bool
    reason: str


def _normalize_query_key(key: str) -> str:
    """Executes _normalize_query_key logic."""
    normalized = key.strip().lower().lstrip("&")
    while normalized.startswith("amp;"):
        normalized = normalized[4:]
    return normalized


def _normalized_query_pairs(
    raw_pairs: list[tuple[str, str]], force_english: bool
) -> list[tuple[str, str]]:
    """Normalize and sort query pairs while preserving semantic keys."""
    query_pairs: list[tuple[str, str]] = []
    for key, value in raw_pairs:
        normalized_key = _normalize_query_key(key)
        if not normalized_key:
            continue
        if normalized_key in VOLATILE_QUERY_KEYS:
            continue
        query_pairs.append((normalized_key, value))

    if force_english:
        # Always force a deterministic English hint and replace any existing language value.
        query_pairs = [(k, v) for k, v in query_pairs if k not in LANGUAGE_QUERY_KEYS]
        query_pairs.append(("language", "english"))

    return sorted(query_pairs, key=lambda item: item[0].lower())


def _normalize_hostbill_pseudo_route_query(raw_query: str, force_english: bool) -> str | None:
    """Preserve HostBill `index.php?/cart/...` pseudo-route queries without percent-encoding the route."""
    if not raw_query.startswith("/") or "/cart/" not in raw_query.lower():
        return None

    route_part, separator, remainder = raw_query.partition("&")
    raw_pairs = parse_qsl(remainder, keep_blank_values=True) if separator else []
    query_pairs = _normalized_query_pairs(raw_pairs, force_english=force_english)

    if not query_pairs:
        return route_part
    return f"{route_part}&{urlencode(query_pairs, doseq=True)}"


def normalize_url(url: str, base_url: str | None = None, force_english: bool = False) -> str:
    """Executes normalize_url logic."""
    if base_url:
        url = urljoin(base_url, url)

    parsed = urlparse(url.strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    pseudo_query = _normalize_hostbill_pseudo_route_query(parsed.query, force_english=force_english)
    if pseudo_query is not None:
        return urlunparse((scheme, netloc, path, "", pseudo_query, ""))

    if force_english and not parsed.query and "/cart/&" in path.lower():
        # HostBill path-style cart routes already encode parameters inside the path.
        # Appending `?language=english` would corrupt the route.
        return urlunparse((scheme, netloc, path, "", "", ""))

    raw_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k]
    query_pairs = _normalized_query_pairs(raw_pairs, force_english=force_english)
    query = urlencode(query_pairs, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def canonicalize_for_merge(url: str) -> str:
    """Executes canonicalize_for_merge logic."""
    # Merge key should be stable across runs and keep semantic query keys (pid, gid, id, rp, cat_id).
    return normalize_url(url=url, base_url=None, force_english=False).lower()


def extract_domain(url: str) -> str:
    """Executes extract_domain logic."""
    return urlparse(url).netloc.lower()


def is_same_domain(url: str, base_url: str) -> bool:
    """Executes is_same_domain logic."""
    return extract_domain(url) == extract_domain(base_url)


def classify_url(url: str) -> UrlClassification:
    """Executes classify_url logic."""
    normalized = normalize_url(url)
    lowered = normalized.lower()
    parsed = urlparse(lowered)

    if not parsed.scheme.startswith("http"):
        return UrlClassification(
            url=normalized, is_invalid_product_url=True, reason="non-http-scheme"
        )

    for pattern in INVALID_PATH_PATTERNS:
        if pattern in parsed.path:
            return UrlClassification(
                url=normalized, is_invalid_product_url=True, reason=f"denylist:{pattern}"
            )

    # Filter out non-product cart pages (view cart, checkout, confproduct).
    non_product_actions = ("a=view", "a=checkout")
    if any(action in lowered for action in non_product_actions):
        return UrlClassification(
            url=normalized, is_invalid_product_url=True, reason="cart-action-page"
        )

    # Check rp= route values against invalid path patterns.
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() == "rp":
            route_lower = value.strip().lower()
            for pattern in INVALID_PATH_PATTERNS:
                if pattern in route_lower:
                    return UrlClassification(
                        url=normalized,
                        is_invalid_product_url=True,
                        reason=f"blocked-route:{pattern}",
                    )

    # Keep only likely product/category-like URLs.
    likely_patterns = ("/store/", "cart.php", "/cart/", "cmd=cart", "action=add", "a=add")
    # Also check rp= query routes for /store/ patterns.
    rp_has_store = any(
        "/store/" in v.lower()
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() == "rp"
    )
    if not rp_has_store and not any(pattern in lowered for pattern in likely_patterns):
        return UrlClassification(
            url=normalized, is_invalid_product_url=True, reason="not-product-like"
        )

    return UrlClassification(url=normalized, is_invalid_product_url=False, reason="ok")


def should_skip_discovery_url(url: str) -> tuple[bool, str]:
    """Return whether discoverer should skip crawling this URL."""
    normalized = normalize_url(url, force_english=False)
    lowered = normalized.lower()
    parsed = urlparse(lowered)

    if not parsed.scheme.startswith("http"):
        return True, "non-http-scheme"

    for pattern in INVALID_PATH_PATTERNS:
        if pattern in parsed.path:
            return True, f"blocked-path:{pattern}"

    if parsed.path.endswith(tuple(INVALID_EXTENSIONS)):
        return True, "media-or-static-file"

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for key, value in query_pairs:
        key_lower = _normalize_query_key(key)
        if key_lower == "currency":
            return True, "blocked-query:currency"

        if key_lower in LANGUAGE_QUERY_KEYS:
            language_tag = value.strip().lower()
            if language_tag and language_tag not in ENGLISH_LANGUAGE_TAGS:
                return True, f"non-english-language:{language_tag}"
            continue

        # WHMCS often uses `rp=/route/...` query routes that hide actual page type.
        if key_lower in ROUTE_QUERY_KEYS:
            route_lower = re.sub(r"/{2,}", "/", value.strip().lower())
            if route_lower and not route_lower.startswith("/"):
                route_lower = f"/{route_lower}"
            for pattern in INVALID_PATH_PATTERNS:
                if pattern in route_lower:
                    return True, f"blocked-route:{pattern}"

    return False, "ok"
