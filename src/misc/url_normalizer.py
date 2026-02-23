from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

INVALID_PATH_PATTERNS = (
    "/contact",
    "/contact.php",
    "/announcements",
    "/knowledgebase",
    "/submitticket",
    "/clientarea",
    "/login",
    "/register",
    "/affiliates",
)

VOLATILE_QUERY_KEYS = {
    "sid",
    "session",
    "phpsessid",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}


@dataclass(slots=True)
class UrlClassification:
    url: str
    is_invalid_product_url: bool
    reason: str


def normalize_url(url: str, base_url: str | None = None, force_english: bool = False) -> str:
    if base_url:
        url = urljoin(base_url, url)

    parsed = urlparse(url.strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k]
    query_pairs = [(k, v) for k, v in query_pairs if k.lower() not in VOLATILE_QUERY_KEYS]

    if force_english and not any(k.lower() == "language" for k, _ in query_pairs):
        query_pairs.append(("language", "english"))

    query_pairs = sorted(query_pairs, key=lambda item: item[0].lower())
    query = urlencode(query_pairs, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def canonicalize_for_merge(url: str) -> str:
    # Merge key should be stable across runs and keep semantic query keys (pid, gid, id, rp, cat_id).
    return normalize_url(url=url, base_url=None, force_english=False).lower()


def extract_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_same_domain(url: str, base_url: str) -> bool:
    return extract_domain(url) == extract_domain(base_url)


def classify_url(url: str) -> UrlClassification:
    normalized = normalize_url(url)
    lowered = normalized.lower()
    parsed = urlparse(lowered)

    if not parsed.scheme.startswith("http"):
        return UrlClassification(url=normalized, is_invalid_product_url=True, reason="non-http-scheme")

    for pattern in INVALID_PATH_PATTERNS:
        if pattern in parsed.path:
            return UrlClassification(url=normalized, is_invalid_product_url=True, reason=f"denylist:{pattern}")

    # Keep only likely product/category-like URLs.
    likely_patterns = ("/store/", "cart.php", "/cart/", "cmd=cart", "action=add", "a=add")
    if not any(pattern in lowered for pattern in likely_patterns):
        return UrlClassification(url=normalized, is_invalid_product_url=True, reason="not-product-like")

    return UrlClassification(url=normalized, is_invalid_product_url=False, reason="ok")

