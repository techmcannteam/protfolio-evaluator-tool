"""Replaceable email interface. No SMTP or external SDK is installed or invoked."""


class StubEmailSender:
    def send(self, message):
        return {"status": "simulated", "sent": False}
