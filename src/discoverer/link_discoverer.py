from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.misc.http_client import HttpClient
from src.misc.logger import get_logger
from src.misc.url_normalizer import is_same_domain, normalize_url


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
            lower = url.lower()
            if any(token in lower for token in ("a=add&pid=", "action=add&id=", "/store/")):
                if "/store/" in lower and lower.rstrip("/").count("/") <= 3:
                    category_candidates.add(url)
                else:
                    product_candidates.add(url)
            if "gid=" in lower or "cat_id=" in lower:
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
                    visited.add(url)
                    future_map[pool.submit(self.http_client.get, url, True, False)] = url

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
                    new_links = {link for link in extracted if is_same_domain(link, root)}
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

