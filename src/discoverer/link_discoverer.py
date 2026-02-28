"""Performs BFS crawling to discover product and category links from vendor sites."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from src.misc.config_loader import coerce_positive_int
from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import is_same_domain, normalize_url, should_skip_discovery_url
from src.parsers.hostbill_parser import parse_hostbill_page


@dataclass(slots=True)
class DiscoverResult:
    """Represents DiscoverResult."""

    site_name: str
    base_url: str
    visited_urls: list[str]
    product_candidates: list[str]
    category_candidates: list[str]


class LinkDiscoverer:
    """Represents LinkDiscoverer."""

    def __init__(
        self,
        http_client: HttpClient,
        max_depth: int = 3,
        max_pages: int = 500,
        max_workers: int = 8,
    ) -> None:
        """Executes __init__ logic."""
        self.http_client = http_client
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.max_workers = coerce_positive_int(max_workers, default=8)
        self.logger = get_logger("discoverer")

    @staticmethod
    def _strip_language_param(url: str) -> str:
        """Remove language/lang/locale query params to avoid duplicate crawls."""
        parsed = urlparse(url)
        if parsed.query.startswith("/") and "/cart/" in parsed.query.lower():
            route_part, separator, remainder = parsed.query.partition("&")
            qs = [
                (k, v)
                for k, v in parse_qsl(remainder, keep_blank_values=True)
                if k.lower() not in ("language", "lang", "locale")
            ]
            query = route_part if not qs else f"{route_part}&{urlencode(qs, doseq=True)}"
            return urlunparse(parsed._replace(query=query))
        qs = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in ("language", "lang", "locale")
        ]
        return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

    @staticmethod
    def _document_base_url(soup: BeautifulSoup, page_url: str) -> str:
        """Resolve links against the HTML base href when present."""
        base_tag = soup.select_one("base[href]")
        if not base_tag:
            return page_url
        href = str(base_tag.get("href", "")).strip()
        if not href:
            return page_url
        return urljoin(page_url, href)

    @staticmethod
    def _is_hostbill_like_url(url: str) -> bool:
        """Return whether a URL looks like a HostBill cart page."""
        parsed = urlparse(url)
        lowered = url.lower()
        return (
            "/cart/" in parsed.path.lower()
            or (parsed.query.startswith("/") and "/cart/" in parsed.query.lower())
            or "cmd=cart" in lowered
        )

    @staticmethod
    def _hostbill_slug_url(url: str) -> str | None:
        """Return the normalized `/cart/<slug>` URL when this is a single-slug HostBill route."""
        normalized = normalize_url(LinkDiscoverer._strip_language_param(url), force_english=False)
        parsed = urlparse(normalized)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) != 2 or segments[0].lower() != "cart":
            return None
        return normalized

    @staticmethod
    def _seed_urls(root: str) -> set[str]:
        """Executes _seed_urls logic."""
        # Seed multiple likely catalog entry points so login-redirect roots do not end discovery early.
        candidates = {
            root,
            urljoin(root, "/index.php"),
            urljoin(root, "/cart.php"),
            urljoin(root, "/store"),
            urljoin(root, "/index.php?rp=/store"),
        }
        # Only seed non-language variants to avoid duplicate crawling.
        return {normalize_url(candidate, force_english=False) for candidate in candidates}

    @staticmethod
    def _extract_links(html: str, base_url: str) -> set[str]:
        """Executes _extract_links logic."""
        soup = BeautifulSoup(html, "lxml")
        document_url = LinkDiscoverer._document_base_url(soup, base_url)
        links: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if href:
                links.add(urljoin(document_url, str(href)))

        # Heuristic extraction from script blobs and inline URLs.
        pattern = re.compile(
            r"""(https?://[^'"\s<>]+|(?:/index\.php\?/cart/[^'"\s<>]+|/store/[^'"\s<>]+|/cart/[^'"\s<>]+|cart/[^'"\s<>]+|cart\.php\?[^'"\s<>]+))""",
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            links.add(urljoin(document_url, match.group(1)))

        # Forms with HostBill product IDs.
        for form in soup.select("form"):
            hidden = {
                i.get("name"): i.get("value") for i in form.select("input[type=hidden][name]")
            }
            add_id = str(hidden.get("id", "")).strip()
            if hidden.get("action") == "add" and add_id.isdigit():
                links.add(urljoin(document_url, f"/index.php?/cart/&action=add&id={add_id}"))

        return {normalize_url(LinkDiscoverer._strip_language_param(link)) for link in links}

    @staticmethod
    def _split_candidates(urls: set[str]) -> tuple[set[str], set[str]]:
        """Executes _split_candidates logic."""
        product_candidates: set[str] = set()
        category_candidates: set[str] = set()

        for url in urls:
            parsed = urlparse(url)
            lower = url.lower()
            query = {k.lower(): v for k, v in parse_qsl(parsed.query, keep_blank_values=True)}

            if "a=add&pid=" in lower or "action=add&id=" in lower:
                product_candidates.add(url)

            if "gid=" in lower or "cat_id=" in lower:
                category_candidates.add(url)

            store_path = ""
            path_lower = parsed.path.lower()
            if "/store/" in path_lower:
                store_path = path_lower.split("/store/", 1)[1]
            else:
                rp = str(query.get("rp", "")).lower()
                if rp.startswith("/store/"):
                    store_path = rp.split("/store/", 1)[1]

            if store_path:
                segments = [segment for segment in store_path.split("/") if segment]
                if len(segments) >= 2:
                    product_candidates.add(url)
                elif len(segments) == 1:
                    category_candidates.add(url)
        return product_candidates, category_candidates

    def discover(self, site_name: str, base_url: str) -> DiscoverResult:
        """Executes discover logic."""
        root = normalize_url(base_url)
        visited: set[str] = set()
        current_layer: set[str] = {root}
        product_candidates: set[str] = set()
        category_candidates: set[str] = set()
        dead_links: set[str] = set()
        stop_reason = "max-depth-reached"

        for depth in range(self.max_depth + 1):
            if not current_layer:
                stop_reason = "frontier-empty"
                break
            if len(visited) >= self.max_pages:
                stop_reason = f"max-pages:{self.max_pages}"
                break

            next_layer: set[str] = set()
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                future_map = {}
                for url in current_layer:
                    if len(visited) >= self.max_pages:
                        break
                    if url in visited:
                        continue
                    if not is_same_domain(url, root):
                        continue
                    skip, reason = should_skip_discovery_url(url)
                    if skip:
                        self.logger.debug("discoverer skip url=%s reason=%s", url, reason)
                        continue
                    visited.add(url)
                    # Discoverer should allow FlareSolverr fallback for anti-bot protected pages.
                    future_map[pool.submit(self.http_client.get, url, True)] = url

                processed = 0
                total = len(future_map)
                for future in as_completed(future_map):
                    source_url = future_map[future]
                    processed += 1
                    if processed == 1 or processed % 100 == 0:
                        self.logger.info(
                            "discoverer progress depth=%s site=%s fetched=%s/%s visited=%s products=%s categories=%s",
                            depth,
                            site_name,
                            processed,
                            total,
                            len(visited),
                            len(product_candidates),
                            len(category_candidates),
                        )
                    try:
                        result = future.result()
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning(
                            "discover fetch failed source=%s error=%s", source_url, exc
                        )
                        continue
                    if not result.ok or not result.text or result.status_code == 404:
                        dead_links.add(source_url)
                        if getattr(result, "final_url", None):
                            dead_links.add(result.final_url)
                        continue
                    fetched_url = normalize_url(
                        self._strip_language_param(getattr(result, "final_url", "") or source_url),
                        force_english=False,
                    )
                    parsed_hostbill_page = None
                    if self._is_hostbill_like_url(fetched_url):
                        parsed_hostbill_page = parse_hostbill_page(result.text, result.final_url)
                    extracted = self._extract_links(result.text, result.final_url)
                    new_links: set[str] = set()
                    for link in extracted:
                        if not is_same_domain(link, root):
                            continue
                        skip, reason = should_skip_discovery_url(link)
                        if skip:
                            self.logger.debug(
                                "discoverer skip extracted_url=%s reason=%s", link, reason
                            )
                            continue
                        new_links.add(link)
                    if parsed_hostbill_page and parsed_hostbill_page.is_product:
                        product_candidates.add(fetched_url)
                    else:
                        page_slug_url = self._hostbill_slug_url(fetched_url)
                        if page_slug_url:
                            slug_links = {
                                slug_url
                                for slug_url in (
                                    self._hostbill_slug_url(link) for link in new_links
                                )
                                if slug_url
                            }
                            if len(slug_links) >= 2:
                                category_candidates.add(page_slug_url)
                    next_layer.update(new_links - visited)
                    products, categories = self._split_candidates(new_links)
                    product_candidates.update(products)
                    category_candidates.update(categories)

            if depth == 0 and not product_candidates and not category_candidates:
                # If the root is login/challenge-like, bootstrap known catalog entrypoints.
                next_layer.update(self._seed_urls(root) - visited)

            self.logger.info(
                "discoverer depth=%s site=%s visited=%s frontier=%s products=%s categories=%s",
                depth,
                site_name,
                len(visited),
                len(next_layer),
                len(product_candidates),
                len(category_candidates),
            )
            current_layer = next_layer

            if len(visited) >= self.max_pages:
                stop_reason = f"max-pages:{self.max_pages}"
                break

        self.logger.info(
            "discoverer done site=%s visited=%s products=%s categories=%s stop=%s",
            site_name,
            len(visited),
            len(product_candidates),
            len(category_candidates),
            stop_reason,
        )
        product_candidates -= dead_links
        category_candidates -= dead_links
        return DiscoverResult(
            site_name=site_name,
            base_url=root,
            visited_urls=sorted(visited),
            product_candidates=sorted(product_candidates),
            category_candidates=sorted(category_candidates),
        )
