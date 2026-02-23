from src.misc.telegram_sender import TelegramSender


def test_telegram_sender_prefers_env_credentials(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
    monkeypatch.setenv("TELEGRAM_TOPIC_ID", "env-topic")

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
    assert sender.config.topic_id == "env-topic"


def test_telegram_sender_disables_when_missing_credentials(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_TOPIC_ID", raising=False)

    sender = TelegramSender({"enabled": True, "bot_token": "", "chat_id": "", "topic_id": ""})
    assert sender.config.enabled is False

