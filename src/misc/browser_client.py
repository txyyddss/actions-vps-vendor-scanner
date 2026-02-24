from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.misc.logger import get_logger

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except Exception:  # noqa: BLE001
    sync_playwright = None
    PlaywrightError = RuntimeError


@dataclass(slots=True)
class BrowserFetchResult:
    ok: bool
    status_code: int | None
    final_url: str
    body: str
    cookies: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class BrowserClient:
    def __init__(self, enabled: bool, headless: bool = True, timeout_ms: int = 60000, wait_until: str = "networkidle") -> None:
        self.enabled = enabled
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until
        self.logger = get_logger("browser_client")

    def get(self, url: str, proxy_url: str | None = None) -> BrowserFetchResult:
        if not self.enabled or sync_playwright is None:
            return BrowserFetchResult(ok=False, status_code=None, final_url=url, body="", error="playwright-disabled")

        try:
            with sync_playwright() as p:
                browser_kwargs: dict[str, object] = {"headless": self.headless}
                if proxy_url:
                    browser_kwargs["proxy"] = {"server": proxy_url}

                browser = p.chromium.launch(**browser_kwargs)
                page = browser.new_page()
                response = page.goto(url, timeout=self.timeout_ms, wait_until=self.wait_until)
                page.wait_for_timeout(1200)
                body = page.content()
                final_url = page.url
                status = response.status if response else None
                cookies = page.context.cookies()
                browser.close()
                return BrowserFetchResult(ok=True, status_code=status, final_url=final_url, body=body, cookies=cookies)
        except PlaywrightError as exc:
            self.logger.warning("Playwright fetch failed for %s: %s", url, exc)
            return BrowserFetchResult(ok=False, status_code=None, final_url=url, body="", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Browser fetch unexpected error for %s: %s", url, exc)
            return BrowserFetchResult(ok=False, status_code=None, final_url=url, body="", error=str(exc))
