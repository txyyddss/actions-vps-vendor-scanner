from __future__ import annotations
"""Handles formatting and sending notifications to Telegram channels."""

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.misc.logger import get_logger


def _escape(text: str) -> str:
    """Executes _escape logic."""
    # Conservative escaping for Telegram Markdown mode.
    return (
        text.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("`", "\\`")
    )


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
    """Executes _normalize_topic_id logic."""
    raw = (value or "").strip()
    # Telegram message_thread_id is an integer and only needed for forum-style groups.
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


class TelegramSender:
    """Represents TelegramSender."""
    def __init__(self, cfg: dict[str, Any]) -> None:
        """Executes __init__ logic."""
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
        # Enable if env vars provide credentials (e.g. GitHub Actions secrets),
        # OR if explicitly enabled in config with credentials present.
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
        """Executes _api_url logic."""
        return f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"

    def _throttle(self) -> None:
        """Ensure minimum interval between sends to avoid per-chat rate limits."""
        elapsed = time.monotonic() - self._last_send_time
        if elapsed < self.config.min_send_interval:
            time.sleep(self.config.min_send_interval - elapsed)

    def _send(self, text: str) -> bool:
        """Executes _send logic."""
        if not self.config.enabled:
            self.logger.info("Telegram disabled, skipping message:\n%s", text)
            return False

        # Telegram message length limit
        if len(text) > self.config.max_message_length:
            text = text[: self.config.max_message_length - 20] + "\n\n…(truncated)"

        self._throttle()

        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if self.config.topic_id:
            payload["message_thread_id"] = self.config.topic_id

        for attempt in range(1, self.config.max_retries + 1):
            try:
                with httpx.Client(timeout=20) as client:
                    response = client.post(self._api_url, json=payload)

                if response.status_code == 429:
                    # Respect Telegram's Retry-After header
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

    def _send_chunked(self, lines: list[str], header_lines: int = 0) -> bool:
        """Split long messages into multiple sends to stay within Telegram's limit."""
        header = "\n".join(lines[:header_lines]) if header_lines else ""
        body_lines = lines[header_lines:]

        chunks: list[str] = []
        current_chunk: list[str] = []
        # First chunk includes the header; subsequent chunks do not.
        first_chunk_overhead = len(header) + 1 if header else 0  # +1 for joining newline
        current_len = first_chunk_overhead

        for line in body_lines:
            line_len = len(line) + 1  # +1 for newline
            if current_len + line_len > self.config.max_message_length - 50:  # leave margin
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                # After the first chunk, header is no longer prepended.
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
                text = f"_(cont.)_\n{chunk}"
            else:
                text = chunk
            if not self._send(text):
                all_ok = False
        return all_ok

    def send_product_changes(self, new_urls: list[str], deleted_urls: list[str]) -> bool:
        """Executes send_product_changes logic."""
        lines = [
            "**Stop scrolling: product catalog changed.**",
            "",
            "**Product Delta**",
            f"- Added: **{len(new_urls)}**",
            f"- Deleted: **{len(deleted_urls)}**",
            "",
            "> Review changes below and validate high-impact listings.",
            "",
        ]
        if new_urls:
            lines.append("**New Products**")
            lines.extend(f"- {_escape(url)}" for url in new_urls[:50])
            lines.append("")
        if deleted_urls:
            lines.append("**Deleted Products**")
            lines.extend(f"- {_escape(url)}" for url in deleted_urls[:50])
            lines.append("")
        lines.append("**CTA:** Please review and confirm if any source needs manual override.")
        return self._send_chunked(lines, header_lines=8)

    def send_run_stats(self, title: str, stats: dict[str, Any]) -> bool:
        """Executes send_run_stats logic."""
        lines = [
            f"**{_escape(title)}**",
            "",
            "**Run Statistics**",
        ]
        for key, value in stats.items():
            lines.append(f"- **{_escape(str(key))}**: {_escape(str(value))}")
        lines.extend(
            [
                "",
                "> Pipeline finished. Metrics are now persisted.",
                "",
                "**CTA:** Reply with any anomaly you want investigated.",
            ]
        )
        return self._send("\n".join(lines))

    def send_restock_alerts(self, restocked_urls: list[str]) -> bool:
        """Executes send_restock_alerts logic."""
        if not restocked_urls:
            return False
        lines = [
            "**Restock detected. Buying window may be open.**",
            "",
            "**Restocked Products**",
        ]
        lines.extend(f"- {_escape(url)}" for url in restocked_urls[:50])
        lines.extend(
            [
                "",
                "> Stock was re-validated in the latest run.",
                "",
                "**CTA:** Do you want instant follow-up checks for these SKUs?",
            ]
        )
        return self._send_chunked(lines, header_lines=3)

