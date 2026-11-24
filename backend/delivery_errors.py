"""Delivery outcomes that distinguish safe retries from uncertain acceptance."""


class DeliveryError(Exception):
    def __init__(self, code, status="failed"):
        # Only fixed codes go into the outbox; never credentials or response bodies.
        super().__init__(code)
        self.code = code
        self.status = status
