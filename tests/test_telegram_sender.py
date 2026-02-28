from src.misc.telegram_sender import TelegramSender


def _build_sender(max_message_length: int = 4096) -> TelegramSender:
    return TelegramSender(
        {
            "enabled": True,
            "bot_token": "configured-token",
            "chat_id": "configured-chat",
            "max_message_length": max_message_length,
        }
    )


def _capture_messages(monkeypatch, sender: TelegramSender) -> list[str]:
    messages: list[str] = []

    def fake_send(text: str) -> bool:
        messages.append(text)
        return True

    monkeypatch.setattr(sender, "_send", fake_send)
    return messages


def test_telegram_sender_prefers_env_credentials(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
    monkeypatch.setenv("TELEGRAM_TOPIC_ID", "12345")

    sender = TelegramSender(
        {
            "enabled": True,
            "bot_token": "",
            "chat_id": "",
            "topic_id": "",
        }
    )
    assert sender.config.enabled is True
    assert sender.config.bot_token == "env-token"
    assert sender.config.chat_id == "env-chat"
    assert sender.config.topic_id == 12345


def test_telegram_sender_disables_when_missing_credentials(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_TOPIC_ID", raising=False)

    sender = TelegramSender({"enabled": True, "bot_token": "", "chat_id": "", "topic_id": ""})
    assert sender.config.enabled is False


def test_telegram_sender_ignores_invalid_topic_id(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
    monkeypatch.setenv("TELEGRAM_TOPIC_ID", "not-a-number")

    sender = TelegramSender({"enabled": True})
    assert sender.config.enabled is True
    assert sender.config.topic_id is None


def test_send_product_changes_chunks_without_dropping_links(monkeypatch) -> None:
    sender = _build_sender(max_message_length=700)
    messages = _capture_messages(monkeypatch, sender)

    current_products = [
        {
            "canonical_url": f"https://example.com/products/{idx}",
            "site": f"Vendor {idx % 3}",
            "name_raw": f"Plan {idx}",
            "price_raw": f"${idx} USD",
            "in_stock": idx % 2,
        }
        for idx in range(55)
    ]
    new_urls = [item["canonical_url"] for item in current_products]

    assert sender.send_product_changes(new_urls=new_urls, deleted_urls=[], current_products=current_products)

    combined = "\n".join(messages)
    assert len(messages) > 1
    assert "https://example.com/products/0" in combined
    assert "https://example.com/products/54" in combined
    assert combined.count("https://example.com/products/") == 55


def test_send_product_changes_keeps_normal_product_block_together(monkeypatch) -> None:
    sender = _build_sender(max_message_length=290)
    messages = _capture_messages(monkeypatch, sender)

    current_products = [
        {
            "canonical_url": "https://ex.co/a",
            "site": "Vendor A",
            "name_raw": "Alpha Plan",
            "price_raw": "$10",
            "in_stock": 1,
        },
        {
            "canonical_url": "https://ex.co/b",
            "site": "Vendor B",
            "name_raw": "Bravo Plan",
            "price_raw": "$20",
            "in_stock": 1,
        },
    ]

    sender.send_product_changes(
        new_urls=[item["canonical_url"] for item in current_products],
        deleted_urls=[],
        current_products=current_products,
    )

    assert len(messages) > 1
    assert any(
        "🟢 *In Stock* Alpha Plan" in message
        and "🔗 [Open Product](https://ex.co/a)" in message
        for message in messages
    )


def test_send_product_changes_uses_previous_metadata_for_deleted_products(monkeypatch) -> None:
    sender = _build_sender()
    messages = _capture_messages(monkeypatch, sender)

    deleted_url = "https://example.com/legacy"
    previous_products = [
        {
            "canonical_url": deleted_url,
            "site": "Legacy Vendor",
            "name_raw": "Legacy Plan",
            "price_raw": "$99",
            "in_stock": 0,
        }
    ]

    sender.send_product_changes(
        new_urls=[],
        deleted_urls=[deleted_url],
        current_products=[],
        previous_products=previous_products,
    )

    combined = "\n".join(messages)
    assert "🗑 *Removed Products*" in combined
    assert "🔴 *Out of Stock* Legacy Plan" in combined
    assert "*Price:* $99" in combined
    assert "https://example.com/legacy" in combined


def test_send_stock_change_alerts_include_links_prices_and_unique_entries(monkeypatch) -> None:
    sender = _build_sender()
    messages = _capture_messages(monkeypatch, sender)

    changed_items = [
        {
            "canonical_url": "https://example.com/restock",
            "site": "Vendor A",
            "name_raw": "Restock Plan",
            "price_raw": "$10",
            "in_stock": 1,
            "restocked": True,
            "destocked": False,
            "changed": True,
        },
        {
            "canonical_url": "https://example.com/oos",
            "site": "Vendor B",
            "name_raw": "OOS Plan",
            "price_raw": "$20",
            "in_stock": 0,
            "restocked": False,
            "destocked": True,
            "changed": True,
        },
    ]

    sender.send_stock_change_alerts(changed_items)

    combined = "\n".join(messages)
    assert "🟢 *Back In Stock*" in combined
    assert "🔴 *Went Out Of Stock*" in combined
    assert "🟢 *In Stock* Restock Plan" in combined
    assert "🔴 *Out of Stock* OOS Plan" in combined
    assert combined.count("*Price:*") == 2
    assert "🔗 [Open Product](https://example.com/restock)" in combined
    assert "🔗 [Open Product](https://example.com/oos)" in combined
    assert combined.count("https://example.com/restock") == 1
