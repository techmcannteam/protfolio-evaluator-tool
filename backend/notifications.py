"""Replaceable SMTP sender, disabled by default; tests inject network-free stubs."""

import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from .delivery_errors import DeliveryError


class StubEmailSender:
    def send(self, message):
        return {"status": "simulated", "sent": False}


class SmtpEmailSender:
    def __init__(self, settings, smtp_factory=None):
        self.settings = settings
        self.smtp_factory = smtp_factory

    @property
    def configured(self):
        s = self.settings
        return bool(
            s.smtp_host
            and s.smtp_username
            and s.smtp_password
            and s.smtp_security in ("starttls", "ssl")
            and s.smtp_port in (465, 587)
        )

    def send(self, message):
        s = self.settings
        if not s.enable_email:
            return {"status": "disabled", "sent": False}
        if not all(
            (
                s.smtp_host,
                s.smtp_username,
                s.smtp_password,
                message.get("from"),
                message.get("to"),
            )
        ):
            return {"status": "needs_configuration", "sent": False}
        if s.smtp_security not in ("starttls", "ssl") or s.smtp_port not in (465, 587):
            return {"status": "needs_configuration", "sent": False}
        mail = EmailMessage()
        mail["From"] = message["from"]
        mail["To"] = ", ".join(message["to"])
        mail["Subject"] = message["subject"]
        mail["Date"] = formatdate(message.get("created_at"), usegmt=True)
        digest = hashlib.sha256(message["delivery_id"].encode()).hexdigest()
        mail["Message-ID"] = f"<{digest}@portfolio-evaluator.local>"
        mail.set_content(message["text"])
        if message.get("html"):
            mail.add_alternative(message["html"], subtype="html")
        smtp = None
        sending = False
        try:
            context = ssl.create_default_context()
            factory = self.smtp_factory or (
                smtplib.SMTP_SSL if s.smtp_security == "ssl" else smtplib.SMTP
            )
            options = {"timeout": 15}
            if s.smtp_security == "ssl":
                options["context"] = context
            smtp = factory(s.smtp_host, s.smtp_port, **options)
            smtp.ehlo()
            if s.smtp_security == "starttls":
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(s.smtp_username, s.smtp_password)
            sending = True
            refused = smtp.send_message(
                mail, from_addr=message["from"], to_addrs=message["to"]
            )
            if refused:
                # Some recipients may already have received it. Do not resend to all.
                raise DeliveryError("smtp_partial_acceptance", "uncertain")
            return {"status": "sent", "sent": True}
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError) as exc:
            raise DeliveryError("smtp_rejected") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise DeliveryError(
                "smtp_acceptance_unknown" if sending else "smtp_connection_failed",
                "uncertain" if sending else "failed",
            ) from exc
        finally:
            if smtp:
                # A failed QUIT must not turn an accepted message into a retry.
                try:
                    smtp.close()
                except OSError:
                    pass
