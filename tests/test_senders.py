import smtplib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from backend.config import Settings
from backend.delivery_errors import DeliveryError
from backend.follow_up_boss import EVENTS_URL, FubSender, evaluation_event
from backend.notifications import SmtpEmailSender


def settings(**kwargs):
    return Settings(
        enable_fub=True,
        enable_email=True,
        fub_api_key="test-key",
        fub_system="Test System",
        fub_system_key="test-system-key",
        smtp_host="smtp.example.com",
        smtp_username="test-user",
        smtp_password="test-password",
        **kwargs,
    )


def event():
    return evaluation_event(
        {"name": "Test Owner", "email": "owner@example.com"},
        "home",
        52,
        "Synthetic result",
    )


def message():
    return {
        "from": "results@example.com",
        "to": ["owner@example.com"],
        "subject": "Your evaluation",
        "text": "Test result",
        "html": "<p>Test result</p>",
        "delivery_id": "stable-id:owner_email",
        "created_at": 1700000000,
    }


def test_fub_sender_uses_events_auth_and_preserves_routing():
    http = Mock()
    http.post.return_value = SimpleNamespace(status_code=201)
    payload = event()
    assert FubSender(settings(), http)(payload) == {"status": "sent", "sent": True}
    args = http.post.call_args
    assert args.args == (EVENTS_URL,)
    assert args.kwargs["json"] == payload
    assert payload["person"]["assignedUserId"] == 52
    assert "home-evaluation" in payload["person"]["tags"]
    assert args.kwargs["auth"] == ("test-key", "")
    assert args.kwargs["headers"]["X-System-Key"] == "test-system-key"
    assert args.kwargs["allow_redirects"] is False
    http.post.assert_called_once()


@pytest.mark.parametrize(
    "code,status",
    [
        (200, "sent"),
        (201, "sent"),
        (204, "ignored"),
        (400, "failed"),
        (401, "failed"),
        (429, "failed"),
        (500, "uncertain"),
        (302, "uncertain"),
    ],
)
def test_fub_outcomes(code, status):
    http = Mock()
    http.post.return_value = SimpleNamespace(status_code=code)
    sender = FubSender(settings(), http)
    if status in {"sent", "ignored"}:
        assert sender(event())["status"] == status
    else:
        with pytest.raises(DeliveryError) as raised:
            sender(event())
        assert raised.value.status == status
    http.post.assert_called_once()


@pytest.mark.parametrize(
    "error,status",
    [
        (requests.ConnectTimeout(), "failed"),
        (requests.ReadTimeout(), "uncertain"),
        (requests.ConnectionError(), "uncertain"),
    ],
)
def test_fub_timeouts_do_not_retry_in_sender(error, status):
    http = Mock()
    http.post.side_effect = error
    with pytest.raises(DeliveryError) as raised:
        FubSender(settings(), http)(event())
    assert raised.value.status == status
    http.post.assert_called_once()


def test_flags_block_real_sender_transports_even_with_credentials():
    s = settings()
    s.enable_fub = s.enable_email = False
    http, factory = Mock(), Mock()
    assert FubSender(s, http)(event())["status"] == "disabled"
    assert SmtpEmailSender(s, factory).send(message())["status"] == "disabled"
    http.post.assert_not_called()
    factory.assert_not_called()


@pytest.mark.parametrize("security,port", [("starttls", 587), ("ssl", 465)])
def test_smtp_multipart_tls_and_stable_message_id(security, port):
    factory = Mock()
    smtp = factory.return_value
    smtp.send_message.return_value = {}
    sender = SmtpEmailSender(settings(smtp_security=security, smtp_port=port), factory)
    assert sender.send(message()) == {"status": "sent", "sent": True}
    mail = smtp.send_message.call_args.args[0]
    assert mail["From"] == "results@example.com" and mail["To"] == "owner@example.com"
    assert (
        mail.get_body(preferencelist=("plain",)).get_content().strip() == "Test result"
    )
    assert (
        mail.get_body(preferencelist=("html",)).get_content().strip()
        == "<p>Test result</p>"
    )
    if security == "starttls":
        smtp.starttls.assert_called_once()
        calls = [call[0] for call in smtp.method_calls]
        assert (
            calls.index("starttls") < calls.index("login") < calls.index("send_message")
        )
    else:
        assert "context" in factory.call_args.kwargs
        smtp.starttls.assert_not_called()
    smtp.login.assert_called_once_with("test-user", "test-password")
    original_id = mail["Message-ID"]
    sender.send(message())
    assert smtp.send_message.call_args.args[0]["Message-ID"] == original_id
    assert "test-password" not in mail.as_string()


@pytest.mark.parametrize(
    "stage,error,status",
    [
        ("login", smtplib.SMTPAuthenticationError(535, b"private response"), "failed"),
        ("send_message", smtplib.SMTPDataError(451, b"private response"), "failed"),
        ("send_message", TimeoutError("private response"), "uncertain"),
        (
            "send_message",
            smtplib.SMTPServerDisconnected("private response"),
            "uncertain",
        ),
    ],
)
def test_smtp_failure_classification(stage, error, status):
    factory = Mock()
    getattr(factory.return_value, stage).side_effect = error
    with pytest.raises(DeliveryError) as raised:
        SmtpEmailSender(settings(), factory).send(message())
    assert raised.value.status == status
    assert "private" not in str(raised.value)


def test_smtp_partial_acceptance_is_not_safely_retryable():
    factory = Mock()
    factory.return_value.send_message.return_value = {"one@example.com": (550, b"No")}
    with pytest.raises(DeliveryError) as raised:
        SmtpEmailSender(settings(), factory).send(message())
    assert raised.value.status == "uncertain"


def test_smtp_does_not_require_real_credentials_for_stub_tests():
    factory = Mock()
    assert (
        SmtpEmailSender(Settings(enable_email=True), factory).send(message())["status"]
        == "needs_configuration"
    )
    factory.assert_not_called()
