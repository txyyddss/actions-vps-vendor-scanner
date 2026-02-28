from __future__ import annotations
"""Handles formatting and sending notifications to Telegram channels."""

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.misc.logger import get_logger


def _escape_md2(text: str) -> str:
    """Escape text for Telegram MarkdownV2 format."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    result = []
    for ch in text:
        if ch in special_chars:
            result.append("\\")
        result.append(ch)
    return "".join(result)


def _stock_label(in_stock: int) -> str:
    """Convert in_stock integer to human-readable label."""
    if in_stock == 1:
        return "🟢 In Stock"
    if in_stock == 0:
        return "🔴 Out of Stock"
    return "⚪ Unknown"


def _stock_emoji(in_stock: int) -> str:
    """Short emoji for stock status."""
    if in_stock == 1:
        return "🟢"
    if in_stock == 0:
        return "🔴"
    return "⚪"


@dataclass(slots=True)
class TelegramConfig:
    """Represents TelegramConfig."""
    enabled: bool
    bot_token: str
    chat_id: str
    topic_id: int | None = None
    max_message_length: int = 4096
    max_retries: int = 5
    base_retry_delay: float = 1.0
    min_send_interval: float = 1.5


def _normalize_topic_id(value: str) -> int | None:
    """Parse topic_id from string; returns None if invalid."""
    raw = (value or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


class TelegramSender:
    """Telegram notification sender with rate-limiting and retry logic."""
    def __init__(self, cfg: dict[str, Any]) -> None:
        # Allow config to override which env var names to read.
        bot_token_env = str(cfg.get("bot_token_env", "TELEGRAM_BOT_TOKEN"))
        chat_id_env = str(cfg.get("chat_id_env", "TELEGRAM_CHAT_ID"))
        topic_id_env = str(cfg.get("topic_id_env", "TELEGRAM_TOPIC_ID"))

        env_bot_token = os.getenv(bot_token_env, "").strip()
        env_chat_id = os.getenv(chat_id_env, "").strip()
        env_topic_id = os.getenv(topic_id_env, "").strip()

        configured_enabled = bool(cfg.get("enabled", False))
        bot_token = env_bot_token or str(cfg.get("bot_token", "")).strip()
        chat_id = env_chat_id or str(cfg.get("chat_id", "")).strip()
        topic_id = _normalize_topic_id(env_topic_id or str(cfg.get("topic_id", "")))
        has_env_credentials = bool(env_bot_token and env_chat_id)
        enabled = bool(bot_token and chat_id) and (has_env_credentials or configured_enabled)

        self.config = TelegramConfig(
            enabled=enabled,
            bot_token=bot_token,
            chat_id=chat_id,
            topic_id=topic_id,
            max_message_length=int(cfg.get("max_message_length", 4096)),
            max_retries=int(cfg.get("max_retries", 5)),
            base_retry_delay=float(cfg.get("base_retry_delay", 1.0)),
            min_send_interval=float(cfg.get("min_send_interval", 1.5)),
        )
        self.logger = get_logger("telegram")
        self._last_send_time: float = 0.0

        if configured_enabled and not enabled:
            self.logger.warning("Telegram is enabled in config but credentials are missing.")

    @property
    def _api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"

    def _throttle(self) -> None:
        """Ensure minimum interval between sends to avoid per-chat rate limits."""
        elapsed = time.monotonic() - self._last_send_time
        if elapsed < self.config.min_send_interval:
            time.sleep(self.config.min_send_interval - elapsed)

    def _send(self, text: str) -> bool:
        if not self.config.enabled:
            self.logger.info("Telegram disabled, skipping message:\n%s", text)
            return False

        if len(text) > self.config.max_message_length:
            text = text[: self.config.max_message_length - 20] + "\n\n…\\(truncated\\)"

        self._throttle()

        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        if self.config.topic_id:
            payload["message_thread_id"] = self.config.topic_id

        for attempt in range(1, self.config.max_retries + 1):
            try:
                with httpx.Client(timeout=20) as client:
                    response = client.post(self._api_url, json=payload)

                if response.status_code == 429:
                    retry_after = self.config.base_retry_delay * (2 ** (attempt - 1))
                    try:
                        body = response.json()
                        retry_after = max(
                            retry_after,
                            float(body.get("parameters", {}).get("retry_after", retry_after)),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    self.logger.warning(
                        "Telegram rate limited (429), attempt %s/%s, retrying in %.1fs",
                        attempt, self.config.max_retries, retry_after,
                    )
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                self._last_send_time = time.monotonic()
                return True

            except httpx.HTTPStatusError as exc:
                self.logger.warning(
                    "Telegram send failed (HTTP %s), attempt %s/%s: %s",
                    exc.response.status_code, attempt, self.config.max_retries, exc,
                )
                if exc.response.status_code >= 500:
                    time.sleep(self.config.base_retry_delay * (2 ** (attempt - 1)))
                    continue
                return False
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Telegram send failed, attempt %s/%s: %s",
                    attempt, self.config.max_retries, exc,
                )
                time.sleep(self.config.base_retry_delay * (2 ** (attempt - 1)))
                continue

        self.logger.error("Telegram send failed after %s attempts", self.config.max_retries)
        return False

    def _send_chunked(self, lines: list[str], header_lines: int = 0) -> bool:
        """Split long messages into multiple sends to stay within Telegram's limit."""
        header = "\n".join(lines[:header_lines]) if header_lines else ""
        body_lines = lines[header_lines:]

        chunks: list[str] = []
        current_chunk: list[str] = []
        first_chunk_overhead = len(header) + 1 if header else 0
        current_len = first_chunk_overhead

        for line in body_lines:
            line_len = len(line) + 1
            if current_len + line_len > self.config.max_message_length - 50:
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
            else:
                current_chunk.append(line)
                current_len += line_len

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        if not chunks:
            return self._send(header or "\n".join(lines))

        all_ok = True
        for i, chunk in enumerate(chunks):
            if i == 0 and header:
                text = f"{header}\n{chunk}"
            elif i > 0:
                text = f"_\\(cont\\.\\)_\n{chunk}"
            else:
                text = chunk
            if not self._send(text):
                all_ok = False
        return all_ok

    # ── Product catalog changes ──────────────────────────────────
    def send_product_changes(
        self,
        new_urls: list[str],
        deleted_urls: list[str],
        products: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Send notification about new and deleted products with rich details."""
        e = _escape_md2
        product_map = {p.get("canonical_url"): p for p in (products or [])}
        lines = [
            "🔔 *Product Catalog Changed*",
            "",
            f"*\\+{len(new_urls)}* new  ·  *\\-{len(deleted_urls)}* removed",
            "",
        ]
        if new_urls:
            lines.append("📦 *New Products:*")
            for url in new_urls[:50]:
                product = product_map.get(url, {})
                name = product.get("name_raw", "")
                site = product.get("site", "")
                stock = _stock_emoji(product.get("in_stock", -1))
                label = f"{e(site)} \\- {e(name)}" if name else e(url)
                lines.append(f"  {stock} {label}")
                if name:
                    lines.append(f"      `{e(url)}`")
            if len(new_urls) > 50:
                lines.append(f"  _\\.\\.\\.and {len(new_urls) - 50} more_")
            lines.append("")
        if deleted_urls:
            lines.append("🗑 *Removed:*")
            for url in deleted_urls[:50]:
                lines.append(f"  • `{e(url)}`")
            if len(deleted_urls) > 50:
                lines.append(f"  _\\.\\.\\.and {len(deleted_urls) - 50} more_")
            lines.append("")
        return self._send_chunked(lines, header_lines=4)

    # ── Run statistics ───────────────────────────────────────────
    def send_run_stats(self, title: str, stats: dict[str, Any]) -> bool:
        """Send run statistics summary with improved formatting."""
        e = _escape_md2
        lines = [
            f"📊 *{e(title)}*",
            "",
        ]
        for key, value in stats.items():
            display_key = str(key).replace("_", " ").title()
            lines.append(f"  *{e(display_key)}:* {e(str(value))}")
        lines.append("")
        return self._send("\n".join(lines))

    # ── Restock alerts ───────────────────────────────────────────
    def send_restock_alerts(
        self,
        restocked_items: list[dict[str, Any]],
    ) -> bool:
        """Send restock alert with product name, site, and price."""
        if not restocked_items:
            return False
        e = _escape_md2
        lines = [
            "🟢 *Restock Detected\\!*",
            "",
            f"*{len(restocked_items)}* product\\(s\\) back in stock:",
            "",
        ]
        for item in restocked_items[:50]:
            url = item.get("canonical_url", "")
            name = item.get("name_raw", "")
            site = item.get("site", "")
            price = item.get("price_raw", "")
            label = f"*{e(site)}* \\- {e(name)}" if name else f"`{e(url)}`"
            price_suffix = f" \\| {e(price)}" if price else ""
            lines.append(f"  🟢 {label}{price_suffix}")
            if name:
                lines.append(f"      `{e(url)}`")
        if len(restocked_items) > 50:
            lines.append(f"  _\\.\\.\\.and {len(restocked_items) - 50} more_")
        lines.append("")
        return self._send_chunked(lines, header_lines=4)

    # ── Stock change alerts (comprehensive) ──────────────────────
    def send_stock_change_alerts(
        self,
        changed_items: list[dict[str, Any]],
    ) -> bool:
        """Send comprehensive stock change notification."""
        if not changed_items:
            return False
        e = _escape_md2
        restocked = [i for i in changed_items if i.get("restocked")]
        destocked = [i for i in changed_items if i.get("destocked")]
        other = [i for i in changed_items if i.get("changed") and not i.get("restocked") and not i.get("destocked")]

        lines = [
            "📈 *Stock Status Changes*",
            "",
            f"🟢 *{len(restocked)}* restocked  ·  🔴 *{len(destocked)}* went OOS  ·  ⚪ *{len(other)}* other",
            "",
        ]
        if restocked:
            lines.append("🟢 *Restocked:*")
            for item in restocked[:20]:
                name = item.get("name_raw", "")
                site = item.get("site", "")
                price = item.get("price_raw", "")
                label = f"*{e(site)}* \\- {e(name)}" if name else f"`{e(item.get('canonical_url', ''))}`"
                price_suffix = f" \\| {e(price)}" if price else ""
                lines.append(f"  {label}{price_suffix}")
            lines.append("")
        if destocked:
            lines.append("🔴 *Out of Stock:*")
            for item in destocked[:20]:
                name = item.get("name_raw", "")
                site = item.get("site", "")
                label = f"*{e(site)}* \\- {e(name)}" if name else f"`{e(item.get('canonical_url', ''))}`"
                lines.append(f"  {label}")
            lines.append("")
        return self._send_chunked(lines, header_lines=4)
