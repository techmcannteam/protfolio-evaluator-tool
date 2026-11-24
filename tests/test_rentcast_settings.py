"""Locked AVM policy, verified using synthetic responses and local SQLite only."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings
from backend.main import create_app
from backend.models import EvaluateRequest, PropertyInput, normalize_address
from backend.providers.base import Transport, cache_key
from backend.providers.rentcast import BASE, RentCast
from backend.repository import Repository

ADDRESS = "100 Example St, Philadelphia, PA 19103"


class Capture:
    def __init__(self, value_status="ok", known=None):
        self.calls = []
        self.value_status = value_status
        self.known = known or {}

    def cached(self, *args):
        return {"status": "ok", "details": self.known, "cached": True}

    def get(self, provider, address, url, params, headers, project):
        self.calls.append((url, params.copy()))
        if url.endswith("/value"):
            return {"status": self.value_status, "cached": True}
        return {"status": "not_found", "cached": True}


@pytest.mark.parametrize("kind", ["Single Family", "Townhouse", "Condo"])
def test_condition_answer_does_not_change_provider_queries_or_cache_keys(kind):
    prop = PropertyInput(address=ADDRESS, property_type=kind, square_footage=950)
    original, updated = Capture(), Capture()
    RentCast(original, "synthetic").evaluate(prop)
    RentCast(updated, "synthetic").evaluate(
        prop.model_copy(update={"recently_updated": True})
    )
    assert original.calls == updated.calls


@pytest.mark.parametrize("kind", ["Single Family", "Townhouse"])
@pytest.mark.parametrize(
    "location,radius",
    [
        ("Philadelphia, PA 19103", 0.5),
        ("PHILADELPHIA, PA 19000", 0.5),  # city independently selects Philadelphia
        ("Other City, PA 19103-1234", 0.5),  # ZIP independently selects Philadelphia
        ("Ardmore, PA 19003", 1.5),
        ("Wayne, PA 19087", 1.5),
        ("Pittsburgh, PA 15201", 1.5),  # no default-radius fallback outside the city
        ("Other City, NJ 08000", 1.5),
        ("New Philadelphia, OH 44663", 1.5),
        ("Philadelphia, PA, 19000", 0.5),
    ],
)
def test_locked_house_value_and_default_rent(kind, location, radius):
    prop = PropertyInput(
        address=f"100 Example St, {location}",
        property_type=kind,
        bedrooms=0,
        bathrooms=1.5,
        square_footage=1200,
    )
    transport = Capture()
    RentCast(transport, "synthetic").evaluate(prop)
    calls = dict(transport.calls)
    base = {"address": normalize_address(prop.address), "propertyType": kind}
    assert calls[BASE + "/avm/value"] == {
        **base,
        "bedrooms": 0,
        "bathrooms": 1.5,
        "squareFootage": 1200,
        "maxRadius": radius,
        "daysOld": 180,
        "compCount": 10,
    }
    assert calls[BASE + "/avm/rent/long-term"] == base


@pytest.mark.parametrize("kind", ["Single Family", "Townhouse"])
def test_missing_house_facts_omitted_and_verified_cached_facts_used(kind):
    prop = PropertyInput(address=ADDRESS, property_type=kind)
    transport = Capture()
    RentCast(transport, "synthetic").evaluate(prop)
    assert not {"bedrooms", "bathrooms", "squareFootage"} & transport.calls[0][1].keys()
    known = {
        "formattedAddress": ADDRESS,
        "propertyType": kind,
        "bedrooms": 3,
        "bathrooms": 2,
        "squareFootage": 1400,
    }
    transport = Capture(known=known)
    RentCast(transport, "synthetic").evaluate(prop.model_copy(update={"bedrooms": 4}))
    assert transport.calls[0][1]["bedrooms"] == 4  # owner wins
    assert transport.calls[0][1]["bathrooms"] == 2
    assert transport.calls[0][1]["squareFootage"] == 1400
    for mismatch in [
        {"formattedAddress": ADDRESS.replace("100", "101")},
        {"addressLine2": "Unit C"},
        {"propertyType": "Multi-Family"},
    ]:
        transport = Capture(known={**known, **mismatch})
        RentCast(transport, "synthetic").evaluate(prop)
        assert "squareFootage" not in transport.calls[0][1]


def test_condo_uses_owner_area_and_default_comp_settings():
    transport = Capture(
        known={
            "formattedAddress": ADDRESS,
            "propertyType": "Condo",
            "squareFootage": 9999,
        }
    )
    RentCast(transport, "synthetic").evaluate(
        PropertyInput(
            address=ADDRESS,
            property_type="Condo",
            bedrooms=2,
            bathrooms=2,
            square_footage=950,
        )
    )
    calls = dict(transport.calls)
    base = {"address": normalize_address(ADDRESS), "propertyType": "Condo"}
    assert calls[BASE + "/avm/value"] == {**base, "squareFootage": 950}
    assert calls[BASE + "/avm/rent/long-term"] == base


@pytest.mark.parametrize("kind", ["Single Family", "Townhouse"])
def test_legacy_value_supplies_only_facts_with_property_record_precedence(kind):
    transport = Capture()

    def cached(provider, address, url, params):
        return {
            "status": "ok",
            "metric": {"estimate": 999999},
            "details": {
                "formattedAddress": ADDRESS,
                "propertyType": kind,
                **(
                    {"bedrooms": 3, "bathrooms": 2, "squareFootage": 1500}
                    if url.endswith("/value")
                    else {"squareFootage": 1600}
                ),
            },
        }

    transport.cached = cached
    result = RentCast(transport, "synthetic").evaluate(
        PropertyInput(address=ADDRESS, property_type=kind)
    )
    assert transport.calls[0][1]["bedrooms"] == 3
    assert transport.calls[0][1]["bathrooms"] == 2
    assert transport.calls[0][1]["squareFootage"] == 1600
    assert result["value"] is None  # never silently restore the legacy metric


def test_condo_missing_owner_area_cannot_use_provider_area_or_call_provider(tmp_path):
    prop = PropertyInput(address=ADDRESS, property_type="Condo")
    transport = Capture(
        known={
            "formattedAddress": ADDRESS,
            "propertyType": "Condo",
            "squareFootage": 9999,
        }
    )
    assert (
        RentCast(transport, "synthetic").evaluate(prop)["status"] == "needs_owner_input"
    )
    assert transport.calls == []
    with pytest.raises(ValidationError, match="owner-provided square footage"):
        EvaluateRequest(addresses=[prop])
    settings = Settings(
        database_url="", database_path=str(tmp_path / "api.db"), vercel=False
    )
    with TestClient(
        create_app(settings, providers=[RentCast(transport, "synthetic")])
    ) as client:
        response = client.post(
            "/api/evaluate",
            json={
                "contact": {"name": "Synthetic Owner", "email": "owner@example.com"},
                "addresses": [prop.model_dump()],
            },
        )
    assert response.status_code == 422 and transport.calls == []


@pytest.mark.parametrize(
    "kind", ["Multi-Family", "Apartment", "Mixed Use", "Manufactured", None]
)
def test_other_value_types_do_not_inherit_house_settings(kind):
    transport = Capture()
    RentCast(transport, "synthetic").evaluate(
        PropertyInput(
            address=ADDRESS,
            property_type=kind,
            bedrooms=3,
            bathrooms=2,
            square_footage=2000,
        )
    )
    expected = {"address": normalize_address(ADDRESS)}
    if kind and kind != "Mixed Use":
        expected["propertyType"] = kind
    assert transport.calls[0] == (BASE + "/avm/value", expected)


@pytest.mark.parametrize(
    "kind",
    [
        "Single Family",
        "Townhouse",
        "Condo",
        "Multi-Family",
        "Apartment",
        "Mixed Use",
        "Manufactured",
        None,
    ],
)
def test_not_found_value_stops_before_any_property_enrichment(kind):
    transport = Capture(value_status="not_found")
    result = RentCast(transport, "synthetic").evaluate(
        PropertyInput(
            address=ADDRESS,
            property_type=kind,
            square_footage=950,
        )
    )
    assert result["status"] == "not_found"
    assert len(transport.calls) == 1 and transport.calls[0][0].endswith("/avm/value")


@pytest.mark.parametrize("kind", ["Single Family", "Townhouse", "Condo"])
def test_old_value_cache_not_reused_but_unchanged_rent_cache_is(tmp_path, kind):
    settings = Settings(
        database_url="",
        database_path=str(tmp_path / "cache.db"),
        vercel=False,
        daily_budget=30,
    )
    repo = Repository(settings)
    repo.initialize()
    address = normalize_address(ADDRESS)
    old_params = {"address": address, "propertyType": kind}
    for endpoint, params, payload in [
        ("/avm/value", old_params, {"metric": {"estimate": 123456}}),
        ("/avm/rent/long-term", old_params, {"metric": {"estimate": 2500}}),
        ("/properties", {"address": address, "limit": 1}, {"details": {}}),
    ]:
        key = cache_key("rentcast", address, BASE + endpoint, params)
        outcome, _, token = repo.claim(key, "rentcast", address, endpoint, 30)
        assert outcome == "fetch"
        repo.finish(key, token, {"status": "ok", **payload}, 86400)
    before = repo.provider_usage("rentcast")
    settings.daily_budget = 0

    class NoHTTP:
        def get(self, *args, **kwargs):
            raise AssertionError("Test must never call a provider")

    result = RentCast(Transport(repo, settings, NoHTTP()), "synthetic").evaluate(
        PropertyInput(address=ADDRESS, property_type=kind, square_footage=950)
    )
    assert result["value"] is None
    assert result["endpoint_status"]["value"] == "budget_exhausted"
    assert result["rent"]["estimate"] == 2500
    assert repo.provider_usage("rentcast") == before


@pytest.mark.parametrize(
    "facts",
    [
        {"bedrooms": -1},
        {"bedrooms": True},
        {"bedrooms": 1.5},
        {"bathrooms": 0},
        {"square_footage": 0},
        {"square_footage": float("nan")},
    ],
)
def test_invalid_subject_facts_rejected(facts):
    with pytest.raises(ValidationError):
        PropertyInput(address=ADDRESS, **facts)
