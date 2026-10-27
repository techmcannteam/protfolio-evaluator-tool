"""Field mapping reused from the McCann avm_comparison.py ATTOM client."""

from ..models import normalize_address
from ..valuation import number

BASE = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"


def project(data, rental=False):
    props = data.get("property")
    if not isinstance(props, list) or not props:
        return {"status": "not_found"}
    if len(props) != 1:
        return {"status": "ambiguous_match"}
    prop = props[0]
    avm = (
        (prop.get("rentalAvm") or {})
        if rental
        else (prop.get("avm") or {}).get("amount", {})
    )
    value = number(avm.get("estimatedRentalValue") if rental else avm.get("value"))
    if value is None:
        return {"status": "not_found"}
    score = number(avm.get("scr"), zero=True)
    fsd = number(avm.get("fsd"), zero=True)
    confidence = (
        max(0, 1 - fsd)
        if fsd is not None
        else min(score / 100, 1)
        if score is not None
        else None
    )
    return {
        "status": "ok",
        "metric": {
            "estimate": value,
            "low": number(avm.get("low")),
            "high": number(avm.get("high")),
            "confidence": confidence,
            "raw_confidence": score,
            "fsd": fsd,
        },
    }


class Attom:
    name = "attom"

    def __init__(self, transport, key):
        self.transport, self.key = transport, key

    def evaluate(self, property):
        if not self.key:
            return {"provider": self.name, "status": "not_configured", "cached": False}
        first, _, rest = property.address.partition(",")
        if not rest:
            return {
                "provider": self.name,
                "status": "address_requires_commas",
                "cached": False,
            }
        params = {"address1": first.strip(), "address2": rest.strip()}
        headers = {"apikey": self.key, "Accept": "application/json"}
        address = normalize_address(property.address)
        value = self.transport.get(
            self.name, address, BASE + "/attomavm/detail", params, headers, project
        )
        if value["status"] in (
            "provider_auth_error",
            "provider_rate_limited",
            "budget_exhausted",
        ):
            return {"provider": self.name, **value}
        rent = self.transport.get(
            self.name,
            address,
            BASE + "/valuation/rentalavm",
            params,
            headers,
            lambda d: project(d, True),
        )
        return {
            "provider": self.name,
            "status": value["status"],
            "value": value.get("metric"),
            "rent": rent.get("metric"),
            "cached": value.get("cached") and rent.get("cached"),
            "endpoint_status": {"value": value["status"], "rent": rent["status"]},
        }
