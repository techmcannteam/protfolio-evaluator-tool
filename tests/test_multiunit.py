import pytest
from pydantic import ValidationError

from backend.config import Assumptions, Settings
from backend.models import EvaluateRequest, PropertyInput
from backend.providers.rentcast import RentCast
from backend.repository import Repository
from backend.service import Evaluator
from backend.valuation import blend, calculate, sum_unit_rents

ADDRESS = "100 Example St, Philadelphia, PA 19103"


class BuildingTransport:
    def __init__(self, count=3, kind="Multi-Family", matched=ADDRESS):
        self.count, self.kind, self.matched = count, kind, matched
        self.calls = []

    def get(self, provider, address, url, params, headers, project):
        self.calls.append((url, params.copy()))
        subject = {"formattedAddress": self.matched, "propertyType": self.kind}
        if url.endswith("/properties"):
            result = project(
                [
                    {
                        **subject,
                        "features": {"unitCount": self.count},
                        "bedrooms": 8,
                        "bathrooms": 4,
                    }
                ]
            )
        elif url.endswith("/value"):
            result = project(
                {
                    "price": 800000,
                    "priceRangeLow": 750000,
                    "priceRangeHigh": 900000,
                    "subjectProperty": subject,
                }
            )
        else:
            rent = 1000 if params.get("bedrooms") == 0 else 2000
            result = project(
                {"rent": rent, "rentRangeLow": rent - 100, "rentRangeHigh": rent + 200}
            )
        return {**result, "cached": True}


def owner(**kwargs):
    return PropertyInput(
        address=ADDRESS,
        is_rental=True,
        unit_count=3,
        owner_source="Owner schedule",
        **kwargs,
    )


def test_unit_rent_summing_deduplicates_layouts_and_preserves_ranges():
    transport = BuildingTransport()
    result = RentCast(transport, "test").evaluate(
        owner(
            unit_mix=[
                {"count": 1, "bedrooms": 0, "bathrooms": 1},
                {"count": 1, "bedrooms": 2, "bathrooms": 1, "square_footage": 900},
                {"count": 1, "bedrooms": 2, "bathrooms": 1, "square_footage": 900},
            ]
        )
    )
    assert result["rent"]["estimate"] == 5000
    assert result["rent"]["low"] == 4700 and result["rent"]["high"] == 5600
    rent_calls = [p for u, p in transport.calls if u.endswith("/long-term")]
    assert len(rent_calls) == 2
    assert all(p["lookupSubjectAttributes"] == "false" for p in rent_calls)
    assert "squareFootage" not in rent_calls[0]
    assert rent_calls[1]["squareFootage"] == 900
    assert result["building"]["unit_count_provenance"] == {
        "source": "owner",
        "label": "Owner schedule",
    }
    assert (
        calculate([result], result["details"], Assumptions())["operating"][
            "annual_rent"
        ]
        == 60000
    )


def test_missing_layout_never_multiplies_legacy_rent_or_building_bedrooms():
    transport = BuildingTransport(count=6)
    result = RentCast(transport, "test").evaluate(owner())
    assert result["rent"] is None and result["unit_estimates"] == []
    assert not any(u.endswith("/long-term") for u, p in transport.calls)
    assert result["building"]["unit_count"] == 3
    assert result["building"]["provider_unit_count"] == 6
    assert result["building"]["review_required"]
    assert calculate([result], result["details"], Assumptions())["operating"] is None


def test_mixed_use_keeps_residential_separate_without_zero_commercial():
    transport = BuildingTransport()
    result = RentCast(transport, "test").evaluate(
        owner(
            property_type="Mixed Use",
            residential_unit_count=2,
            unit_mix=[{"count": 2, "bedrooms": 2, "bathrooms": 1}],
        )
    )
    assert result["residential_rent"]["estimate"] == 4000
    assert result["commercial_rent"] is None and result["rent"] is None
    assert result["commercial_status"] == "needs_agent_review"
    assert (
        result["value"] is None
    )  # Residential value is not a verified mixed-use value.
    assert calculate([result], result["details"], Assumptions())["operating"] is None


@pytest.mark.parametrize(
    "kind,matched",
    [
        ("Land", "2323 Ellsworth St, Philadelphia, PA 19146"),
        ("Apartment", "1914 E Passyunk Ave Unit C, Philadelphia, PA 19148"),
    ],
)
def test_bad_matches_are_withheld_by_full_evaluation(kind, matched):
    address = matched.replace(" Unit C", "")
    source = RentCast(BuildingTransport(kind=kind, matched=matched), "test").evaluate(
        PropertyInput(address=address, unit_count=2, is_rental=True)
    )
    assert source["value"] is None and source["rent"] is None
    assert source["match_warning"] and source["status"] == "needs_agent_review"


def test_scope_mismatch_and_incomplete_bounds_are_not_blended_or_double_multiplied():
    metric = {"estimate": 2000, "low": None, "high": 2500, "scope": "unit"}
    assert sum_unit_rents([{"count": 2, "metric": metric}])["low"] is None
    assert (
        sum_unit_rents([{"count": 2, "metric": {**metric, "scope": "building"}}])
        is None
    )
    sources = [
        {"provider": "a", "rent": metric},
        {"provider": "b", "rent": {**metric, "scope": "building"}},
    ]
    assert blend(sources, "rent") is None
    assert calculate(sources[:1], {}, Assumptions())["rent"] is None


def test_partial_rent_avm_failure_withholds_entire_total():
    transport = BuildingTransport()
    original = transport.get

    def get(provider, address, url, params, headers, project):
        if url.endswith("/long-term") and params["bedrooms"] == 2:
            return {"status": "not_found", "cached": True}
        return original(provider, address, url, params, headers, project)

    transport.get = get
    result = RentCast(transport, "test").evaluate(
        owner(
            unit_mix=[
                {"count": 1, "bedrooms": 0, "bathrooms": 1},
                {"count": 2, "bedrooms": 2, "bathrooms": 1},
            ]
        )
    )
    assert result["rent"] is None and result["residential_rent"] is None


def test_owner_inputs_are_validated_not_inferred():
    for invalid in [
        {"unit_count": 0},
        {"unit_count": True},
        {"unit_count": 2, "residential_unit_count": 3},
        {"unit_count": 2, "unit_mix": [{"count": 1, "bedrooms": 1, "bathrooms": 1}]},
        {
            "unit_count": 2,
            "property_type": "Mixed Use",
            "unit_mix": [{"count": 2, "bedrooms": 1, "bathrooms": 1}],
        },
    ]:
        with pytest.raises(ValidationError):
            PropertyInput(address=ADDRESS, **invalid)
    assert PropertyInput(address=ADDRESS).unit_count is None


def test_actual_rent_is_separate_and_missing_building_rents_do_not_total_zero(tmp_path):
    settings = Settings(
        database_url="", database_path=str(tmp_path / "test.db"), vercel=False
    )
    repo = Repository(settings)
    repo.initialize()
    result = Evaluator(
        repo, [RentCast(BuildingTransport(), "test")], settings
    ).evaluate(EvaluateRequest(addresses=[owner(actual_monthly_rent=12345)]))
    row = result["properties"][0]
    assert row["actual_monthly_rent"]["amount"] == 12345
    assert row["rent"] is None and row["operating"] is None
    assert (
        result["totals"]["monthly_rent"] is None
        and result["totals"]["cap_rate"] is None
    )
    assert row["needs_agent_review"]


def test_attom_disabled_never_constructed(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import main

    def forbidden(*args, **kwargs):
        raise AssertionError("ATTOM must not be constructed while disabled")

    monkeypatch.setattr(main, "Attom", forbidden)
    settings = Settings(
        database_url="",
        database_path=str(tmp_path / "off.db"),
        vercel=False,
        enable_attom=False,
        rentcast_key="",
        attom_key="unused",
    )
    with TestClient(main.create_app(settings)) as client:
        result = client.post("/api/evaluate", json={"contact": {"name": "Synthetic Owner", "email": "owner@example.com"}, "addresses": [ADDRESS]}).json()
    assert [s["provider"] for s in result["properties"][0]["sources"]] == ["rentcast"]
