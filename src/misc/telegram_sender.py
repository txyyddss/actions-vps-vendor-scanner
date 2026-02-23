from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from src.misc.logger import get_logger


def _escape(text: str) -> str:
    # Conservative escaping for Telegram Markdown.
    return (
        text.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )


@dataclass(slots=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str
    topic_id: str | None = None
    tone: str = "professional"


class TelegramSender:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.config = TelegramConfig(
            enabled=bool(cfg.get("enabled", False)),
            bot_token=str(cfg.get("bot_token", "")),
            chat_id=str(cfg.get("chat_id", "")),
            topic_id=str(cfg.get("topic_id", "") or ""),
            tone=str(cfg.get("tone", "professional")),
        )
        self.logger = get_logger("telegram")

    @property
    def _api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"

    def _send(self, text: str) -> bool:
        if not self.config.enabled:
            self.logger.info("Telegram disabled, skipping message:\n%s", text)
            return False

        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if self.config.topic_id:
            payload["message_thread_id"] = self.config.topic_id

        try:
            with httpx.Client(timeout=20) as client:
                response = client.post(self._api_url, json=payload)
                response.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Telegram send failed: %s", exc)
            return False

    def send_product_changes(self, new_urls: list[str], deleted_urls: list[str]) -> bool:
        hook = "**Stop scrolling: product catalog changed.**"
        lines = [
            hook,
            "",
            "**📦 Product Delta**",
            f"• Added: **{len(new_urls)}**",
            f"• Deleted: **{len(deleted_urls)}**",
            "",
            "> Review changes below and validate high-impact listings.",
            "",
        ]
        if new_urls:
            lines.append("**🟢 New Products**")
            lines.extend(f"• {_escape(url)}" for url in new_urls[:20])
            lines.append("")
        if deleted_urls:
            lines.append("**🔴 Deleted Products**")
            lines.extend(f"• {_escape(url)}" for url in deleted_urls[:20])
            lines.append("")
        lines.append("**CTA:** Please review and confirm if any source needs manual override.")
        return self._send("\n".join(lines))

    def send_run_stats(self, title: str, stats: dict[str, Any]) -> bool:
        lines = [
            f"**{_escape(title)}**",
            "",
            "**📊 Run Statistics**",
        ]
        for key, value in stats.items():
            lines.append(f"• **{_escape(str(key))}**: {_escape(str(value))}")
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
        if not restocked_urls:
            return False
        lines = [
            "**Restock detected. Buying window may be open.**",
            "",
            "**🟩 Restocked Products**",
        ]
        lines.extend(f"• {_escape(url)}" for url in restocked_urls[:50])
        lines.extend(["", "> Stock was re-validated in the latest run.", "", "**CTA:** Do you want instant follow-up checks for these SKUs?**"])
        return self._send("\n".join(lines))

