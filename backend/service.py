from concurrent.futures import ThreadPoolExecutor

from .config import DISCLAIMER
from .models import normalize_address
from .valuation import calculate


class Evaluator:
    def __init__(self, repository, providers, settings):
        self.repository, self.providers, self.settings = repository, providers, settings

    def evaluate(self, request, agent=None):
        assumptions = (
            self.settings.defaults.model_copy(
                update=request.assumptions.model_dump(exclude_unset=True)
            )
            if request.assumptions
            else self.settings.defaults
        )

        def evaluate_property(property):
            sources = [provider.evaluate(property) for provider in self.providers]
            details = next((s["details"] for s in sources if s.get("details")), {})
            result = {
                "address": property.address,
                "property_type": property.property_type or details.get("propertyType"),
                "is_rental": property.is_rental,
                "normalized_address": normalize_address(property.address),
                "details": details,
                "sources": sources,
                "cached": all(s.get("cached") for s in sources),
                **calculate(sources, details, assumptions),
            }
            if not property.is_rental and result["operating"]:
                result["operating"]["cap_rate"] = None
            result["warnings"] = []
            if any(s.get("match_warning") for s in sources):
                result["warnings"].append(
                    "Provider address, unit or property type differs from your input; ask your agent to verify."
                )
            if not result["value"]:
                statuses = {s["status"] for s in sources}
                result["error"] = {
                    "code": "address_not_found"
                    if statuses == {"not_found"}
                    else "estimate_unavailable",
                    "message": "No value estimate was found for this address."
                    if statuses == {"not_found"}
                    else "An estimate is temporarily unavailable. Please try later or ask your agent.",
                }
            else:
                if not result["rent"]:
                    result["warnings"].append(
                        "Rent unavailable; NOI and cap rate cannot be calculated."
                    )
                result["estimate_id"] = self.repository.save_estimate(
                    property.address, agent, result
                )
            return result

        with ThreadPoolExecutor(max_workers=min(5, len(request.addresses))) as pool:
            results = list(pool.map(evaluate_property, request.addresses))
        values = [r["value"] for r in results if r["value"]]
        rents = [r["rent"] for r in results if r["rent"]]
        rentals = [r for r in results if r["is_rental"]]
        operating = [r for r in rentals if r["operating"]]
        operating_value = sum(r["value"]["estimate"] for r in operating)
        noi = sum(r["operating"]["annual_noi"] for r in operating)
        complete = len(values) == len(results) and len(operating) == len(rentals)
        totals = {
            "estimated_value": round(sum(v["estimate"] for v in values), 2),
            "value_low": sum(v["low"] for v in values)
            if values and all(v["low"] is not None for v in values)
            else None,
            "value_high": sum(v["high"] for v in values)
            if values and all(v["high"] is not None for v in values)
            else None,
            "monthly_rent": sum(r["estimate"] for r in rents),
            "annual_noi": round(noi, 2) if operating else None,
            "cap_rate": round(noi / operating_value, 6)
            if operating_value and len(operating) == len(rentals)
            else None,
            "complete": complete,
            "properties_requested": len(results),
            "properties_valued": len(values),
            "properties_with_noi": len(operating),
        }
        return {
            "properties": results,
            "totals": totals,
            "agent": agent,
            "disclaimer": DISCLAIMER,
        }
