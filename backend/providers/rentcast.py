from ..models import normalize_address
from ..valuation import number

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
        ]
        if record.get(key) is not None
    }
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

    def evaluate(self, property):
        if not self.key:
            return {"provider": self.name, "status": "not_configured", "cached": False}
        address = normalize_address(property.address)
        params = {"address": address}
        if property.property_type:
            params["propertyType"] = property.property_type
        headers = {"X-Api-Key": self.key, "Accept": "application/json"}
        value = self.transport.get(
            self.name, address, BASE + "/avm/value", params, headers, project_avm
        )
        if value["status"] in (
            "provider_auth_error",
            "provider_rate_limited",
            "budget_exhausted",
            "not_found",
        ):
            return {"provider": self.name, **value}
        rent = self.transport.get(
            self.name,
            address,
            BASE + "/avm/rent/long-term",
            params,
            headers,
            lambda d: project_avm(d, True),
        )
        records = self.transport.get(
            self.name,
            address,
            BASE + "/properties",
            {"address": address, "limit": 1},
            headers,
            project_records,
        )
        details = {**value.get("details", {}), **records.get("details", {})}
        matched = details.get("formattedAddress")
        warning = False
        if matched:
            try:
                warning = normalize_address(matched) != address
            except ValueError:
                warning = True
        return {
            "provider": self.name,
            "status": "ok" if value.get("metric") else value["status"],
            "value": value.get("metric"),
            "rent": rent.get("metric"),
            "details": details,
            "match_warning": warning,
            "cached": all(x.get("cached") for x in [value, rent, records]),
            "endpoint_status": {
                "value": value["status"],
                "rent": rent["status"],
                "property": records["status"],
            },
        }
