import hashlib
import json
import time
from typing import Protocol

import requests


class Provider(Protocol):
    name: str

    def evaluate(self, property): ...


class Transport:
    def __init__(self, repository, settings, session=None):
        self.repository, self.settings = repository, settings
        self.session = session or requests

    def get(self, provider, address, url, params, headers, project):
        key = hashlib.sha256(
            json.dumps(
                [
                    provider,
                    url,
                    address,
                    {k: v for k, v in params.items() if not k.startswith("address")},
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        outcome, payload, token = self.repository.claim(
            key, provider, address, url.split("/")[-1], self.settings.daily_budget
        )
        # A concurrent request owns this provider call. Briefly wait for its cache.
        if outcome == "busy":
            for _ in range(10):
                time.sleep(0.2)
                outcome, payload, token = self.repository.claim(
                    key,
                    provider,
                    address,
                    url.split("/")[-1],
                    self.settings.daily_budget,
                )
                if outcome != "busy":
                    break
        if outcome == "cached":
            return {**payload, "cached": True}
        if outcome != "fetch":
            return {"status": outcome, "cached": False}
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=(5, 15),
                allow_redirects=False,
            )
            if response.status_code == 200:
                payload = project(response.json())
            elif response.status_code in (404, 422):
                payload = {"status": "not_found"}
            elif response.status_code in (401, 403):
                payload = {"status": "provider_auth_error"}
            elif response.status_code == 429:
                payload = {"status": "provider_rate_limited"}
            else:
                payload = {"status": "provider_unavailable"}
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ):
            payload = {"status": "provider_unavailable"}
        ttl = (
            30 * 86400
            if payload["status"] == "ok"
            else (86400 if payload["status"] == "not_found" else 300)
        )
        self.repository.finish(key, token, payload, ttl)
        return {**payload, "cached": False}
