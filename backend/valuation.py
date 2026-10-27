import math
from statistics import median

from .config import DISCLAIMER


def number(value, zero=False):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and (n >= 0 if zero else n > 0) else None
    except (TypeError, ValueError):
        return None


def blend(sources, metric):
    valid = [
        s[metric]
        for s in sources
        if s.get(metric) and number(s[metric].get("estimate"))
    ]
    if not valid:
        return None
    estimate = median(x["estimate"] for x in valid)
    lows = [x["low"] for x in valid if number(x.get("low"))]
    highs = [x["high"] for x in valid if number(x.get("high"))]
    spread = (
        max(x["estimate"] for x in valid) - min(x["estimate"] for x in valid)
    ) / estimate
    scores = [x["confidence"] for x in valid if x.get("confidence") is not None]
    confidence = "medium"
    if spread > 0.20 or any(s < 0.6 for s in scores):
        confidence = "low"
    elif len(valid) > 1 and spread <= 0.1 and all(s >= 0.8 for s in scores):
        confidence = "high"
    if any(x.get("match_warning") for x in sources):
        confidence = "low"
    return {
        "estimate": round(estimate, 2),
        "low": min(lows) if lows else None,
        "high": max(highs) if highs else None,
        "confidence": confidence,
        "sources": [
            s["provider"]
            for s in sources
            if s.get(metric) and s[metric].get("estimate")
        ],
    }


def calculate(sources, details, assumptions):
    value, rent = blend(sources, "value"), blend(sources, "rent")
    expenses = None
    if value and rent:
        annual = rent["estimate"] * 12
        actual = number(details.get("annual_taxes"), zero=True)
        taxes = (
            assumptions.annual_taxes if assumptions.annual_taxes is not None else actual
        )
        tax_source = (
            "override" if assumptions.annual_taxes is not None else "property_record"
        )
        if taxes is None:
            taxes = value["estimate"] * assumptions.fallback_tax_rate
            tax_source = "fallback"
        insurance = value["estimate"] * assumptions.insurance_rate
        management = annual * assumptions.management
        maintenance = annual * assumptions.maintenance
        noi = (
            annual * (1 - assumptions.vacancy)
            - taxes
            - insurance
            - management
            - maintenance
        )
        expenses = {
            "annual_rent": round(annual, 2),
            "annual_taxes": round(taxes, 2),
            "tax_source": tax_source,
            "annual_insurance": round(insurance, 2),
            "annual_management": round(management, 2),
            "annual_maintenance": round(maintenance, 2),
            "annual_vacancy": round(annual * assumptions.vacancy, 2),
            "annual_noi": round(noi, 2),
            "cap_rate": round(noi / value["estimate"], 6),
        }
    return {
        "value": value,
        "rent": rent,
        "operating": expenses,
        "assumptions": assumptions.model_dump(),
        "assumptions_status": "Placeholders; pending confirmation with Ben.",
        "disclaimer": DISCLAIMER,
    }
