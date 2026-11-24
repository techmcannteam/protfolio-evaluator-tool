import json

import pytest
from pydantic import ValidationError

from backend.config import Assumptions, Settings
from backend.valuation import calculate

SOURCES = [
    {"provider": "rentcast", "value": {"estimate": 400000}, "rent": {"estimate": 2500}}
]


def test_default_expenses_unchanged():
    result = calculate(SOURCES, {"annual_taxes": 4200}, Assumptions())["operating"]
    assert result["annual_maintenance"] == 1500
    assert result["annual_insurance"] == 2000
    assert result["annual_noi"] == 18400


@pytest.mark.parametrize(
    "mode,insurance,maintenance,noi",
    [
        ("per_unit", 1200, 1800, 18900),
        ("percent_rent", 1800, 1800, 18300),
    ],
)
def test_annual_per_unit_and_rent_percent(mode, insurance, maintenance, noi):
    a = Assumptions(
        maintenance_mode="per_unit",
        maintenance_per_unit=600,
        insurance_mode=mode,
        insurance_per_unit=400,
        insurance_rent_rate=0.06,
    )
    result = calculate(SOURCES, {"annual_taxes": 4200}, a, unit_count=3)["operating"]
    assert result["annual_insurance"] == insurance
    assert result["annual_maintenance"] == maintenance
    assert result["annual_noi"] == noi


def test_missing_units_withholds_noi_instead_of_assuming_one():
    result = calculate(
        SOURCES, {}, Assumptions(insurance_mode="per_unit", insurance_per_unit=500)
    )
    assert (
        result["operating"] is None and result["expense_status"] == "needs_unit_count"
    )


def test_config_block_and_validation(monkeypatch):
    monkeypatch.setenv(
        "EXPENSE_ASSUMPTIONS_JSON",
        json.dumps(
            {
                "vacancy": 0.03,
                "insurance_mode": "percent_rent",
                "insurance_rent_rate": 0.04,
            }
        ),
    )
    assert Settings().defaults.vacancy == 0.03
    assert Settings().defaults.insurance_rent_rate == 0.04
    with pytest.raises(ValidationError):
        Assumptions(maintenance_per_unit=-1)
    with pytest.raises(ValidationError):
        Assumptions(insurance_mode="monthly_guess")
