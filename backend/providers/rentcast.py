from ..models import normalize_address
from ..valuation import number, sum_unit_rents
from .buildings import normalized_match

BASE = "https://api.rentcast.io/v1"


def property_details(record):
    result = {
        key: record.get(key)
        for key in [
            "formattedAddress",
            "propertyType",
            "bedrooms",
            "bathrooms",
            "squareFootage",
            "yearBuilt",
            "lastSaleDate",
            "lastSalePrice",
            "id",
            "addressLine2",
            "assessorID",
            "zoning",
        ]
        if record.get(key) is not None
    }
    count = number((record.get("features") or {}).get("unitCount"))
    if count is not None and count.is_integer():
        result["unitCount"] = int(count)
    taxes = record.get("propertyTaxes") or {}
    for year in sorted(taxes, reverse=True):
        tax = number(taxes[year].get("total"), zero=True)
        if tax is not None:
            result.update(annual_taxes=tax, tax_year=year)
            break
    return result


def project_avm(data, rental=False):
    field = "rent" if rental else "price"
    estimate = number(data.get(field))
    if not estimate:
        return {"status": "not_found"}
    low, high = (
        number(data.get(field + "RangeLow")),
        number(data.get(field + "RangeHigh")),
    )
    if low and high and not low <= estimate <= high:
        low = high = None
    return {
        "status": "ok",
        "metric": {"estimate": estimate, "low": low, "high": high, "confidence": None},
        "details": property_details(data.get("subjectProperty") or {}),
    }


def project_records(data):
    if not isinstance(data, list) or len(data) != 1:
        return {"status": "not_found" if not data else "ambiguous_match"}
    return {"status": "ok", "details": property_details(data[0])}


class RentCast:
    name = "rentcast"

    def __init__(self, transport, key):
        self.transport, self.key = transport, key

    def record(self, property):
        if not self.key:
            return {"status": "not_configured"}
        address = normalize_address(property.address)
        return self.transport.get(
            self.name,
            address,
            BASE + "/properties",
            {"address": address, "limit": 1},
            {"X-Api-Key": self.key, "Accept": "application/json"},
            project_records,
        )

    def building_record(self, property):
        """Selective enrichment for missing building metadata; original keys stay valid."""
        from .buildings import resolve_building_records

        if not self.key:
            return {"status": "not_configured"}
        address = normalize_address(property.address)
        return self.transport.get(
            self.name,
            address,
            BASE + "/properties",
            {"address": address, "limit": 500},
            {"X-Api-Key": self.key, "Accept": "application/json"},
            lambda data: resolve_building_records(data, address),
        )

    def evaluate(self, property):
        if not self.key:
            return {"provider": self.name, "status": "not_configured", "cached": False}
        address = normalize_address(property.address)
        params = {"address": address}
        if property.property_type and property.property_type != "Mixed Use":
            params["propertyType"] = property.property_type
        headers = {"X-Api-Key": self.key, "Accept": "application/json"}
        value = self.transport.get(
            self.name, address, BASE + "/avm/value", params, headers, project_avm
        )
        if value["status"] in (
            "provider_auth_error",
            "provider_rate_limited",
        ):
            return {"provider": self.name, **value}
        multi = bool(
            (property.unit_count and property.unit_count > 1)
            or property.property_type in {"Multi-Family", "Apartment", "Mixed Use"}
        )
        records = self.building_record(property) if multi else self.record(property)
        details = {**value.get("details", {}), **records.get("details", {})}
        if not multi and (
            details.get("propertyType") in {"Multi-Family", "Apartment", "Land"}
            or details.get("unitCount", 0) > 1
            or (normalized_match(details) and normalized_match(details) != address)
        ):
            multi = True
            records = self.building_record(property)
        if multi:
            return self.evaluate_building(property, value, records)
        rent = self.transport.get(
            self.name,
            address,
            BASE + "/avm/rent/long-term",
            params,
            headers,
            lambda d: project_avm(d, True),
        )
        matched = details.get("formattedAddress")
        warning = False
        if matched:
            try:
                warning = normalize_address(matched) != address
            except ValueError:
                warning = True
        type_warning = bool(
            property.property_type
            and details.get("propertyType")
            and property.property_type != details["propertyType"]
        )
        return {
            "provider": self.name,
            "property_type_warning": type_warning,
            "status": "ok" if value.get("metric") else value["status"],
            "value": value.get("metric"),
            "rent": rent.get("metric"),
            "details": details,
            "match_warning": warning or type_warning,
            "cached": all(x.get("cached") for x in [value, rent, records]),
            "endpoint_status": {
                "value": value["status"],
                "rent": rent["status"],
                "property": records["status"],
            },
            "endpoint_details": {
                "value": value.get("details", {}),
                "rent": rent.get("details", {}),
                "property": records.get("details", {}),
            },
        }

    def evaluate_building(self, property, value, records):
        address = normalize_address(property.address)
        provider_count = records.get("unit_count")
        count = (
            property.unit_count if property.unit_count is not None else provider_count
        )
        res_count = property.residential_unit_count
        mixed = property.property_type == "Mixed Use" or (
            res_count is not None and count is not None and res_count < count
        )
        if not mixed and res_count is None:
            res_count = count
        provenance = lambda owner: {
            "source": "owner" if owner else "rentcast",
            "label": property.owner_source if owner else "RentCast property record",
        }
        mix = (
            [u.model_dump() for u in property.unit_mix]
            if property.unit_mix
            else records.get("unit_mix")
        )
        # A provider mix built for a different count cannot silently follow an override.
        if not property.unit_mix and (mixed or count != provider_count):
            mix = None
        warnings = []
        if (
            property.unit_count is not None
            and provider_count is not None
            and count != provider_count
        ):
            warnings.append(
                f"Owner unit count ({count}) overrides RentCast count ({provider_count}); verify with your agent."
            )
        if count is None:
            warnings.append("Unit count unknown; needs agent review.")
        if res_count is None or (res_count > 0 and not mix):
            warnings.append(
                "Residential unit layouts are missing; needs agent review. Building bedrooms are not per-unit layouts."
            )
        if mixed:
            warnings.append(
                "Commercial rent needs agent review; building rent, NOI and cap rate are unavailable until commercial income is verified."
            )
        record_details = records.get("details", {})
        subject = value.get("details", {})
        whole_match = (
            records.get("status") == "ok"
            and normalized_match(record_details) == address
        )
        subject_match = normalized_match(subject) == address and not subject.get(
            "addressLine2"
        )
        value_type = subject.get("propertyType") or record_details.get("propertyType")
        valid_value = (
            whole_match
            and subject_match
            and value_type in {"Multi-Family", "Apartment"}
            and record_details.get("propertyType") != "Land"
        )
        # Mixed-use valuation scope is not supported by the residential provider.
        if mixed:
            valid_value = False
        if not whole_match or not valid_value:
            warnings.append(
                "Provider whole-building value match or scope is unverified; needs agent review."
            )
        metric = (
            {**value["metric"], "scope": "building"}
            if valid_value and value.get("metric")
            else None
        )
        components, responses = [], [value, records]
        statuses = {"value": value["status"], "property": records["status"]}
        if (
            mix
            and res_count
            and sum(u["count"] for u in mix) == res_count
            and whole_match
        ):
            # Combine identical owner rows before requesting a representative AVM.
            groups = {}
            for u in mix:
                key = (u["bedrooms"], u["bathrooms"], u.get("square_footage"))
                groups[key] = groups.get(key, 0) + u["count"]
            for (beds, baths, area), n in groups.items():
                params = {
                    "address": address,
                    "propertyType": "Apartment"
                    if count >= 5 or mixed
                    else "Multi-Family",
                    "bedrooms": beds,
                    "bathrooms": baths,
                    "lookupSubjectAttributes": "false",
                }
                if area is not None:
                    params["squareFootage"] = area
                response = self.transport.get(
                    self.name,
                    address,
                    BASE + "/avm/rent/long-term",
                    params,
                    {"X-Api-Key": self.key, "Accept": "application/json"},
                    lambda d: project_avm(d, True),
                )
                responses.append(response)
                statuses[f"unit_rent_{len(components) + 1}"] = response["status"]
                rent_subject = response.get("details", {})
                # lookupSubjectAttributes=false may omit subjectProperty. Any returned
                # conflicting address still invalidates this component.
                matched = normalized_match(rent_subject)
                unit_metric = response.get("metric")
                if (
                    rent_subject.get("formattedAddress") and matched != address
                ) or rent_subject.get("propertyType") == "Land":
                    unit_metric = None
                    warnings.append(
                        "A unit-rent endpoint returned a different subject; needs agent review."
                    )
                components.append(
                    {
                        "count": n,
                        "bedrooms": beds,
                        "bathrooms": baths,
                        "square_footage": area,
                        "metric": {**unit_metric, "scope": "unit"}
                        if unit_metric
                        else None,
                        "subject": rent_subject,
                        "status": response["status"],
                    }
                )
        residential = sum_unit_rents(components)
        if components and not residential:
            warnings.append(
                "At least one unit rent is unavailable; no partial residential total is presented."
            )
        rent = residential if not mixed else None
        building = {
            "unit_count": count,
            "provider_unit_count": provider_count,
            "residential_unit_count": res_count,
            "mixed_use": mixed,
            "category": "mixed_use"
            if mixed
            else "multi_family_5_plus"
            if count and count >= 5
            else "multi_family_2_4"
            if count and count >= 2
            else "unknown",
            "unit_count_provenance": provenance(property.unit_count is not None)
            if count is not None
            else None,
            "unit_mix_provenance": provenance(bool(property.unit_mix)) if mix else None,
            "unit_mix": mix,
            "match_verified": whole_match,
            "review_required": bool(warnings) or rent is None or metric is None,
        }
        return {
            "provider": self.name,
            "status": "ok" if metric else "needs_agent_review",
            "value": metric,
            "rent": rent,
            "residential_rent": residential,
            "commercial_rent": None,
            "commercial_status": "needs_agent_review" if mixed else "not_applicable",
            "details": record_details if whole_match else {},
            "building": building,
            "unit_estimates": components,
            "warnings": warnings,
            "match_warning": not valid_value
            or (provider_count is not None and count != provider_count),
            "cached": all(r.get("cached") for r in responses),
            "endpoint_status": statuses,
            "endpoint_details": {
                "value": subject,
                "property": record_details,
                "candidates": records.get("candidates", []),
            },
            "unverified_value": value.get("metric") if not valid_value else None,
        }
