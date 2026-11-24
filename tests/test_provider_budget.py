"""Regression coverage for the previously unapplied preview fixes."""

import hashlib
import json
from datetime import datetime

import pytest

from backend.config import Settings
from backend.models import EvaluateRequest, PropertyInput, normalize_address
from backend.providers.attom import Attom
from backend.providers.base import Transport, cache_key
from backend.providers.rentcast import RentCast
from backend.repository import Repository
from backend.service import Evaluator

ADDRESS = "100 Example St, Philadelphia, PA 19103"


@pytest.fixture
def repository(tmp_path):
    settings = Settings(
        database_url="",
        database_path=str(tmp_path / "test.db"),
        vercel=False,
        daily_budget=0,
    )
    repo = Repository(settings)
    repo.initialize()
    return repo, settings


@pytest.mark.parametrize("provider_cls", [RentCast, Attom])
def test_blocked_value_retains_cached_rent(provider_cls, repository):
    repo, settings = repository

    class CachedRent:
        def get(self, provider, address, url, params, headers, project):
            if url.endswith(("/long-term", "/rentalavm")):
                return {
                    "status": "ok",
                    "cached": True,
                    "metric": {"estimate": 2500, "low": None, "high": None},
                }
            return {"status": "budget_exhausted", "cached": False}

    result = Evaluator(repo, [provider_cls(CachedRent(), "test")], settings).evaluate(
        EvaluateRequest(addresses=[PropertyInput(address=ADDRESS, is_rental=True)])
    )["properties"][0]
    assert result["value"] is None
    assert result["rent"]["estimate"] == 2500
    assert result["operating"] is None
    assert result["error"]["code"] == "budget_exhausted"
    assert "UTC" in result["error"]["message"]
    assert datetime.fromisoformat(result["error"]["reset_at"]).hour == 0


def test_denial_logged_without_reservation_or_http(repository):
    repo, settings = repository

    class NoHTTP:
        def get(self, *args, **kwargs):
            raise AssertionError("A budget denial must not reach HTTP")

    result = Transport(repo, settings, NoHTTP()).get(
        "rentcast", ADDRESS, "https://example.test/value", {}, {}, lambda d: d
    )
    assert result["status"] == "budget_exhausted" and result["reset_at"]
    assert repo.provider_usage("rentcast") == 0
    with repo.transaction() as db:
        rows = db.execute("SELECT status,http_status FROM provider_calls").fetchall()
    assert len(rows) == 1
    assert dict(rows[0]) == {"status": "budget_exhausted", "http_status": None}


@pytest.mark.parametrize("status", [200, 400])
def test_http_status_retained_in_cache_and_audit(repository, status):
    repo, settings = repository
    settings.daily_budget = 1

    class HTTP:
        calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1

            class Response:
                status_code = status

                def json(self):
                    return {"status": "ok"}

            return Response()

    http = HTTP()
    transport = Transport(repo, settings, http)
    args = ("rentcast", ADDRESS, "https://example.test/value", {}, {}, lambda d: d)
    first, second = transport.get(*args), transport.get(*args)
    assert first["http_status"] == second["http_status"] == status
    assert second["cached"] and http.calls == 1
    with repo.transaction() as db:
        row = db.execute(
            "SELECT http_status FROM provider_calls WHERE cached=0"
        ).fetchone()
    assert row["http_status"] == status


def test_cache_key_compatibility_and_read_only_plan(repository):
    repo, _ = repository
    address = normalize_address(ADDRESS)
    params = {"address": address, "limit": 1}
    expected = hashlib.sha256(
        json.dumps(
            ["rentcast", "https://example.test/properties", address, {"limit": 1}],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert (
        cache_key("rentcast", address, "https://example.test/properties", params)
        == expected
    )
    assert repo.cache_entries([expected]) == {}
    assert repo.provider_usage("rentcast") == 0
    repo.initialize()  # Audit schema migration is idempotent.
    with repo.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM provider_cache").fetchone()[0] == 0
