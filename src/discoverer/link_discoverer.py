from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import is_same_domain, normalize_url, should_skip_discovery_url


@dataclass(slots=True)
class DiscoverResult:
    site_name: str
    base_url: str
    visited_urls: list[str]
    product_candidates: list[str]
    category_candidates: list[str]


class LinkDiscoverer:
    def __init__(self, http_client: HttpClient, max_depth: int = 3, max_pages: int = 500, max_workers: int = 8) -> None:
        self.http_client = http_client
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.max_workers = max_workers
        self.logger = get_logger("discoverer")

    @staticmethod
    def _extract_links(html: str, base_url: str) -> set[str]:
        soup = BeautifulSoup(html, "lxml")
        links: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if href:
                links.add(urljoin(base_url, str(href)))

        # Heuristic extraction from script blobs and inline URLs.
        pattern = re.compile(
            r"(https?://[^'\"\\s<>]+|(?:/index\\.php\\?/cart/[^'\"\\s<>]+|/store/[^'\"\\s<>]+|cart\\.php\\?[^'\"\\s<>]+))",
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            links.add(urljoin(base_url, match.group(1)))

        # Forms with HostBill product IDs.
        for form in soup.select("form"):
            hidden = {i.get("name"): i.get("value") for i in form.select("input[type=hidden][name]")}
            if hidden.get("action") == "add" and hidden.get("id"):
                links.add(urljoin(base_url, f"/index.php?/cart/&action=add&id={hidden['id']}"))

        return {normalize_url(link) for link in links}

    @staticmethod
    def _split_candidates(urls: set[str]) -> tuple[set[str], set[str]]:
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
        root = normalize_url(base_url)
        visited: set[str] = set()
        current_layer: set[str] = {root}
        product_candidates: set[str] = set()
        category_candidates: set[str] = set()

        for depth in range(self.max_depth + 1):
            if not current_layer or len(visited) >= self.max_pages:
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
                    # Discoverer should allow full fallback chain for anti-bot protected pages.
                    future_map[pool.submit(self.http_client.get, url, True, True)] = url

                for future in as_completed(future_map):
                    source_url = future_map[future]
                    try:
                        result = future.result()
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning("discover fetch failed source=%s error=%s", source_url, exc)
                        continue
                    if not result.ok or not result.text:
                        continue
                    extracted = self._extract_links(result.text, result.final_url)
                    new_links: set[str] = set()
                    for link in extracted:
                        if not is_same_domain(link, root):
                            continue
                        skip, reason = should_skip_discovery_url(link)
                        if skip:
                            self.logger.debug("discoverer skip extracted_url=%s reason=%s", link, reason)
                            continue
                        new_links.add(link)
                    next_layer.update(new_links - visited)
                    products, categories = self._split_candidates(new_links)
                    product_candidates.update(products)
                    category_candidates.update(categories)

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

        return DiscoverResult(
            site_name=site_name,
            base_url=root,
            visited_urls=sorted(visited),
            product_candidates=sorted(product_candidates),
            category_candidates=sorted(category_candidates),
        )
