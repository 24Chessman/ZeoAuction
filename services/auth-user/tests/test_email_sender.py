"""Unit tests for transactional email delivery without making network requests."""

import json
from unittest.mock import MagicMock

from app.adapters import email_sender
from app.settings import Settings


def settings(**overrides: str) -> Settings:
    values = {
        "database_url": "postgresql://test",
        "refresh_ttl_days": 14,
        "accept_seed_password": False,
        "seed_password": "test-password",
        "gmail_user": "sender@gmail.com",
        "brevo_api_key": "test-api-key",
        "brevo_sender_email": "sender@gmail.com",
    }
    values.update(overrides)
    return Settings(**values)


def test_brevo_delivery_preserves_html_and_text_templates(monkeypatch) -> None:
    response = MagicMock()
    response.status = 201
    response.read.return_value = b'{"messageId":"brevo-test-message-id"}'
    response.__enter__.return_value = response
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr(email_sender, "urlopen", urlopen)

    sent = email_sender._send_email_sync(
        "buyer@example.com",
        "Your code",
        "Code: 123456",
        "<strong>123456</strong>",
        settings(),
    )

    assert sent is True
    request = urlopen.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://api.brevo.com/v3/smtp/email"
    assert request.get_method() == "POST"
    assert payload["sender"] == {"name": "ZeoAuction", "email": "sender@gmail.com"}
    assert payload["to"] == [{"email": "buyer@example.com"}]
    assert payload["textContent"] == "Code: 123456"
    assert payload["htmlContent"] == "<strong>123456</strong>"


def test_brevo_is_preferred_when_api_key_is_configured(monkeypatch) -> None:
    brevo = MagicMock(return_value=True)
    smtp = MagicMock(return_value=False)
    monkeypatch.setattr(email_sender, "_send_brevo_email_sync", brevo)
    monkeypatch.setattr(email_sender, "_send_smtp_email_sync", smtp)

    assert email_sender._send_email_sync("buyer@example.com", "s", "t", "h", settings())
    brevo.assert_called_once()
    smtp.assert_not_called()
