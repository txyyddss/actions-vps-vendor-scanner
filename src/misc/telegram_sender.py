"""Handles formatting and sending notifications to Telegram channels."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.misc.logger import get_logger

CONTINUATION_MARKER = "_\\(cont\\.\\)_"
MESSAGE_SAFETY_MARGIN = 64
BLOCK_SAFETY_MARGIN = 120
DEFAULT_PRODUCT_NAME = "Unnamed Product"
DEFAULT_SITE_NAME = "Unknown Site"
DEFAULT_PRICE = "Unknown"
DEFAULT_LINK_LABEL = "Open Product"


def _escape_md2(text: str) -> str:
    """Escape text for Telegram MarkdownV2 format."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    result: list[str] = []
    for ch in str(text):
        if ch in special_chars:
            result.append("\\")
        result.append(ch)
    return "".join(result)


def _escape_md2_link_target(url: str) -> str:
    """Escape link target characters that break Telegram MarkdownV2 links."""
    target = str(url or "").strip()
    return target.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _stock_status(in_stock: int) -> tuple[str, str]:
    """Return a consistent icon + label tuple for product availability."""
    try:
        value = int(in_stock)
    except (TypeError, ValueError):
        value = -1

    if value == 1:
        return "🟢", "In Stock"
    if value == 0:
        return "🔴", "Out of Stock"
    return "⚪", "Unknown"


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


@dataclass(slots=True)
class _MessageBlock:
    """Atomic content block used by chunked Telegram messages."""

    text: str
    force_new_message_before: bool = False


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

    @property
    def _safe_message_length(self) -> int:
        """Return a safe chunk size below Telegram's hard limit."""
        return max(80, self.config.max_message_length - MESSAGE_SAFETY_MARGIN)

    @property
    def _safe_block_length(self) -> int:
        """Reserve space for headers and section labels around each product block."""
        return max(60, self._safe_message_length - BLOCK_SAFETY_MARGIN)

    @staticmethod
    def _join_segments(segments: list[str]) -> str:
        """Join message segments with paragraph spacing."""
        return "\n\n".join(segment for segment in segments if segment)

    @staticmethod
    def _product_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
        """Sort products for human-readable ordering."""
        site = str(item.get("site") or DEFAULT_SITE_NAME).lower()
        name = str(item.get("name_raw") or DEFAULT_PRODUCT_NAME).lower()
        url = str(item.get("canonical_url") or "")
        return (site, name, url)

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
            text = text[: self.config.max_message_length - 18] + "\n\n_\\(truncated\\)_"

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
                        attempt,
                        self.config.max_retries,
                        retry_after,
                    )
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                self._last_send_time = time.monotonic()
                return True

            except httpx.HTTPStatusError as exc:
                self.logger.warning(
                    "Telegram send failed (HTTP %s), attempt %s/%s: %s",
                    exc.response.status_code,
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                if exc.response.status_code >= 500:
                    time.sleep(self.config.base_retry_delay * (2 ** (attempt - 1)))
                    continue
                return False
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Telegram send failed, attempt %s/%s: %s",
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                time.sleep(self.config.base_retry_delay * (2 ** (attempt - 1)))
                continue

        self.logger.error("Telegram send failed after %s attempts", self.config.max_retries)
        return False

    def _format_product_blocks(self, item: dict[str, Any]) -> list[_MessageBlock]:
        """Render a product into one or more atomic chunk blocks."""
        icon, status_label = _stock_status(item.get("in_stock", -1))
        name = str(item.get("name_raw") or DEFAULT_PRODUCT_NAME).strip() or DEFAULT_PRODUCT_NAME
        site = str(item.get("site") or DEFAULT_SITE_NAME).strip() or DEFAULT_SITE_NAME
        price = str(item.get("price_raw") or DEFAULT_PRICE).strip() or DEFAULT_PRICE
        url = str(item.get("canonical_url") or "").strip()

        metadata_lines = [
            f"{icon} *{_escape_md2(status_label)}* {_escape_md2(name)}",
            f"*Site:* {_escape_md2(site)}",
            f"*Price:* {_escape_md2(price)}",
        ]

        if url:
            link_line = f"🔗 [{_escape_md2(DEFAULT_LINK_LABEL)}]({_escape_md2_link_target(url)})"
        else:
            link_line = f"🔗 *Link:* {_escape_md2('N/A')}"

        full_block = "\n".join([*metadata_lines, link_line])
        if url and len(full_block) > self._safe_block_length:
            return [
                _MessageBlock("\n".join(metadata_lines)),
                _MessageBlock(f"🔗 {_escape_md2(url)}", force_new_message_before=True),
            ]
        return [_MessageBlock(full_block)]

    def _send_sectioned(
        self,
        header_lines: list[str],
        sections: list[tuple[str, list[_MessageBlock]]],
    ) -> bool:
        """Send chunked messages while keeping product blocks and section headers intact."""
        rendered_sections = [(title, blocks) for title, blocks in sections if blocks]
        if not rendered_sections:
            return False

        header_text = "\n".join(line for line in header_lines if line)
        messages: list[str] = []
        current_segments = [header_text] if header_text else []

        def fits(additions: list[str]) -> bool:
            candidate = self._join_segments(current_segments + [part for part in additions if part])
            return len(candidate) <= self._safe_message_length

        def flush() -> None:
            if current_segments:
                messages.append(self._join_segments(current_segments))

        for section_title, blocks in rendered_sections:
            first_block = blocks[0]
            section_start = [section_title, first_block.text]
            if first_block.force_new_message_before and current_segments:
                flush()
                current_segments = [CONTINUATION_MARKER, section_title]
            if not fits(section_start):
                header_only = bool(header_text and not messages and current_segments == [header_text])
                if header_only:
                    current_segments.extend(section_start)
                else:
                    flush()
                    current_segments = [CONTINUATION_MARKER, section_title, first_block.text]
            else:
                current_segments.extend(section_start)

            for block in blocks[1:]:
                if block.force_new_message_before and current_segments:
                    flush()
                    current_segments = [CONTINUATION_MARKER, section_title]
                if not fits([block.text]):
                    flush()
                    current_segments = [CONTINUATION_MARKER, section_title, block.text]
                else:
                    current_segments.append(block.text)

        flush()

        all_ok = True
        for message in messages:
            if not self._send(message):
                all_ok = False
        return all_ok

    def _build_section_blocks(self, items: list[dict[str, Any]]) -> list[_MessageBlock]:
        """Flatten a sorted item list into chunkable product blocks."""
        blocks: list[_MessageBlock] = []
        for item in sorted(items, key=self._product_sort_key):
            blocks.extend(self._format_product_blocks(item))
        return blocks

    # Product catalog changes
    def send_product_changes(
        self,
        new_urls: list[str],
        deleted_urls: list[str],
        current_products: list[dict[str, Any]] | None = None,
        previous_products: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Send notification about new and deleted products with full product details."""
        if not new_urls and not deleted_urls:
            return False

        current_map = {item.get("canonical_url"): item for item in (current_products or [])}
        previous_map = {item.get("canonical_url"): item for item in (previous_products or [])}

        new_items = [current_map.get(url, {"canonical_url": url}) for url in new_urls]
        deleted_items = [previous_map.get(url, {"canonical_url": url}) for url in deleted_urls]

        sections: list[tuple[str, list[_MessageBlock]]] = []
        if new_items:
            sections.append(("🆕 *New Products*", self._build_section_blocks(new_items)))
        if deleted_items:
            sections.append(("🗑 *Removed Products*", self._build_section_blocks(deleted_items)))

        header_lines = [
            "📦 *Product Catalog Changed*",
            f"*{len(new_urls)}* new • *{len(deleted_urls)}* removed",
        ]
        return self._send_sectioned(header_lines, sections)

    # Run statistics
    def send_run_stats(self, title: str, stats: dict[str, Any]) -> bool:
        """Send run statistics summary with improved formatting."""
        e = _escape_md2
        lines = [
            f"📈 *{e(title)}*",
            "",
        ]
        for key, value in stats.items():
            display_key = str(key).replace("_", " ").title()
            lines.append(f"  *{e(display_key)}:* {e(str(value))}")
        lines.append("")
        return self._send("\n".join(lines))

    # Restock alerts
    def send_restock_alerts(
        self,
        restocked_items: list[dict[str, Any]],
    ) -> bool:
        """Compatibility wrapper that routes restock notifications through the unified sender."""
        if not restocked_items:
            return False
        return self.send_stock_change_alerts(restocked_items)

    # Stock change alerts (comprehensive)
    def send_stock_change_alerts(
        self,
        changed_items: list[dict[str, Any]],
    ) -> bool:
        """Send comprehensive stock change notification."""
        if not changed_items:
            return False

        restocked = [item for item in changed_items if item.get("restocked")]
        destocked = [item for item in changed_items if item.get("destocked")]
        other = [
            item
            for item in changed_items
            if not item.get("restocked") and not item.get("destocked")
        ]

        sections: list[tuple[str, list[_MessageBlock]]] = []
        if restocked:
            sections.append(("🟢 *Back In Stock*", self._build_section_blocks(restocked)))
        if destocked:
            sections.append(("🔴 *Went Out Of Stock*", self._build_section_blocks(destocked)))
        if other:
            sections.append(("⚪ *Status Changed / Unknown*", self._build_section_blocks(other)))

        header_lines = [
            "📊 *Stock Status Changes*",
            (
                f"🟢 *{len(restocked)}* back in stock • "
                f"🔴 *{len(destocked)}* out of stock • "
                f"⚪ *{len(other)}* other"
            ),
        ]
        return self._send_sectioned(header_lines, sections)
