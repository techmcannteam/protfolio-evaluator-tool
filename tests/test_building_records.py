"""Synthetic regressions for whole-building resolution and provider-only ranges."""

from backend.models import normalize_address
from backend.providers.buildings import resolve_building_records
from backend.providers.rentcast import property_details
from backend.valuation import blend


def record(address, kind="Multi-Family", **kwargs):
    return {"formattedAddress": address, "propertyType": kind, **kwargs}


def test_1914_passyunk_does_not_select_unit_c_as_building():
    address = "1914 E Passyunk Ave, Philadelphia, PA 19148"
    unit = record(
        "1914 E Passyunk Ave Unit C, Philadelphia, PA 19148",
        "Apartment",
        bedrooms=1,
        bathrooms=1,
    )
    result = resolve_building_records([unit], normalize_address(address))
    assert result["status"] == "ambiguous_match" and result["match_warning"]
    assert "details" not in result and result["unit_mix"] is None
    building = record(address, features={"unitCount": 3})
    result = resolve_building_records([unit, building], normalize_address(address))
    assert result["details"]["formattedAddress"] == address
    assert result["unit_count"] == 3 and result["unit_mix"] is None


def test_2323_ellsworth_rejects_land_and_resolves_exact_building_only():
    address = "2323 Ellsworth St, Philadelphia, PA 19146"
    land = record(address, "Land")
    result = resolve_building_records([land], normalize_address(address))
    assert result["status"] == "ambiguous_match" and result["match_warning"]
    building = record(address, features={"unitCount": 2})
    result = resolve_building_records([land, building], normalize_address(address))
    assert result["details"]["propertyType"] == "Multi-Family"
    assert (
        resolve_building_records([building, building], normalize_address(address))[
            "status"
        ]
        == "ambiguous_match"
    )


def test_unit_count_preserved_and_missing_count_stays_unknown():
    assert property_details({"features": {"unitCount": 3}})["unitCount"] == 3
    for value in [None, 0, -1, True, 2.5, "invalid"]:
        assert "unitCount" not in property_details({"features": {"unitCount": value}})
    address = "100 Example St, Philadelphia, PA 19103"
    result = resolve_building_records([record(address)], normalize_address(address))
    assert result["unit_count"] is None and result["unit_mix"] is None


def test_unit_mix_requires_all_verified_unit_layouts():
    address = "100 Example St, Philadelphia, PA 19103"
    building = record(address, features={"unitCount": 3}, bedrooms=8, bathrooms=4)
    a = record(
        "100 Example St Unit A, Philadelphia, PA 19103",
        "Apartment",
        bedrooms=0,
        bathrooms=1,
        squareFootage=500,
    )
    b = record(
        "100 Example St Unit B, Philadelphia, PA 19103",
        "Apartment",
        bedrooms=2,
        bathrooms=1,
        squareFootage=850,
    )
    c = record(
        "100 Example St Unit C, Philadelphia, PA 19103",
        "Apartment",
        bedrooms=2,
        bathrooms=1,
        squareFootage=850,
    )
    assert (
        resolve_building_records([building, a, b], normalize_address(address))[
            "unit_mix"
        ]
        is None
    )
    result = resolve_building_records([building, a, b, c], normalize_address(address))
    assert sorted((m["count"], m["bedrooms"]) for m in result["unit_mix"]) == [
        (1, 0),
        (2, 2),
    ]
    assert (
        resolve_building_records([building], normalize_address(address))["unit_mix"]
        is None
    )


def test_single_provider_keeps_own_bounds_and_never_high_confidence():
    source = {
        "provider": "rentcast",
        "value": {
            "estimate": 500000,
            "low": 410000,
            "high": 640000,
            "confidence": 0.99,
        },
    }
    for sources in [[source], [source, source]]:
        result = blend(sources, "value")
        assert result["low"] == 410000 and result["high"] == 640000
        assert result["confidence"] == "medium"
    result = blend([{**source, "match_warning": True}], "value")
    assert result["confidence"] == "low"
    source["value"]["low"] = None
    assert blend([source], "value")["low"] is None
