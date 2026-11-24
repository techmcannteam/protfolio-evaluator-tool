"""Resolve building records without inventing unit layouts or choosing unit letters."""

import re
from collections import Counter

from ..models import normalize_address
from ..valuation import number


def normalized_match(details):
    try:
        return normalize_address(details.get("formattedAddress", ""))
    except ValueError:
        return None


def building_address(address):
    return re.sub(r"\s+unit\s+[a-z0-9/-]+(?=\s)", "", address)


def resolve_building_records(data, requested_address):
    from .rentcast import property_details

    if not isinstance(data, list) or not data:
        return {"status": "not_found", "unit_count": None, "unit_mix": None}
    candidates = [property_details(record) for record in data]
    exact = [
        r
        for r in candidates
        if normalized_match(r) == requested_address
        and not r.get("addressLine2")
        and r.get("propertyType") != "Land"
    ]
    result = {
        "candidates": candidates,
        "unit_count": None,
        "unit_mix": None,
        "provenance": "rentcast_property_records",
        "projection_version": 2,
    }
    # A full page or duplicate whole-building candidates is not an exact resolution.
    if len(exact) != 1 or len(data) >= 500:
        return {**result, "status": "ambiguous_match", "match_warning": True}
    details = exact[0]
    count = details.get("unitCount")
    result.update(status="ok", details=details, unit_count=count, match_warning=False)
    units = {}
    conflicts = False
    for record in candidates:
        address = normalized_match(record)
        if (
            not address
            or address == requested_address
            or building_address(address) != requested_address
        ):
            continue
        if address in units and units[address] != record:
            conflicts = True
        units[address] = record
    if count == 1 and details.get("propertyType") in {
        "Single Family",
        "Townhouse",
        "Condo",
        "Manufactured",
    }:
        units = {requested_address: details}
    if not count or len(units) != count or conflicts:
        return result
    mix = Counter()
    for unit in units.values():
        beds, baths = (
            number(unit.get("bedrooms"), zero=True),
            number(unit.get("bathrooms")),
        )
        if beds is None or baths is None or unit.get("propertyType") == "Land":
            return result
        mix[(beds, baths, number(unit.get("squareFootage")))] += 1
    result["unit_mix"] = [
        {
            "count": n,
            "bedrooms": beds,
            "bathrooms": baths,
            "square_footage": area,
            "provenance": "rentcast_property_records",
        }
        for (beds, baths, area), n in mix.items()
    ]
    return result
