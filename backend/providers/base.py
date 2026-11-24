import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Protocol

import requests


class Provider(Protocol):
    name: str

    def evaluate(self, property): ...


def cache_key(provider, address, url, params):
    # Preserve keys for identical queries; changed settings produce different keys.
    return hashlib.sha256(
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


def budget_reset():
    return datetime.fromtimestamp(
        (int(time.time() // 86400) + 1) * 86400, UTC
    ).isoformat()


class Transport:
    def __init__(self, repository, settings, session=None):
        self.repository, self.settings = repository, settings
        self.session = session or requests

    def get(self, provider, address, url, params, headers, project):
        key = cache_key(provider, address, url, params)
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
            return {
                "status": outcome,
                "cached": False,
                **(
                    {"reset_at": budget_reset()}
                    if outcome == "budget_exhausted"
                    else {}
                ),
            }
        http_status = None
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=(5, 15),
                allow_redirects=False,
            )
            http_status = response.status_code
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
        payload["http_status"] = http_status
        ttl = (
            30 * 86400
            if payload["status"] == "ok"
            else (86400 if payload["status"] == "not_found" else 300)
        )
        self.repository.finish(key, token, payload, ttl)
        return {**payload, "cached": False}

    def cached(self, provider, address, url, params):
        """Read existing data without reserving a call or changing daily usage."""
        key = cache_key(provider, address, url, params)
        entry = self.repository.cache_entries([key]).get(key, {})
        if entry.get("payload") is not None and entry.get("expires_at", 0) > time.time():
            return {**entry["payload"], "cached": True}
        return None
