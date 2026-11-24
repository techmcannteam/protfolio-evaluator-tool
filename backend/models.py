import re
import unicodedata
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from .config import Assumptions

ALIASES = {
    "street": "st",
    "avenue": "ave",
    "road": "rd",
    "lane": "ln",
    "drive": "dr",
    "boulevard": "blvd",
    "terrace": "ter",
    "circle": "cir",
    "court": "ct",
    "place": "pl",
    "pennsylvania": "pa",
    "apartment": "unit",
    "apt": "unit",
    "suite": "unit",
}


def normalize_address(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    if len(value) > 250 or any(ord(c) < 32 for c in value):
        raise ValueError("Enter a full street address, city, state and ZIP.")
    value = re.sub(r"#\s*", " unit ", value)
    value = re.sub(r"[.,]", " ", value)
    value = " ".join(ALIASES.get(word, word) for word in value.split())
    if not re.fullmatch(r"[0-9][a-z0-9 /\-]+", value) or not re.search(
        r"\b[a-z]{2} \d{5}(?:-\d{4})?$", value
    ):
        raise ValueError("Enter a full street address, city, state and ZIP.")
    if len(value.split()) < 5:
        raise ValueError("Enter a full street address, city, state and ZIP.")
    return value


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, str_strip_whitespace=True
    )


class UnitType(Model):
    count: int = Field(ge=1, le=500, strict=True)
    bedrooms: int = Field(ge=0, le=30, strict=True)
    bathrooms: float = Field(gt=0, le=30)
    square_footage: float | None = Field(None, gt=0, le=100000)


class PropertyInput(Model):
    is_rental: bool = False
    recently_updated: bool | None = Field(None, strict=True)
    address: str = Field(min_length=10, max_length=250)
    property_type: (
        Literal[
            "Single Family",
            "Townhouse",
            "Condo",
            "Multi-Family",
            "Apartment",
            "Manufactured",
            "Mixed Use",
        ]
        | None
    ) = None
    bedrooms: int | None = Field(None, ge=0, le=30, strict=True)
    bathrooms: float | None = Field(None, gt=0, le=30)
    square_footage: float | None = Field(None, gt=0, le=100000)
    unit_count: int | None = Field(None, ge=1, le=500, strict=True)
    residential_unit_count: int | None = Field(None, ge=0, le=500, strict=True)
    unit_mix: list[UnitType] | None = Field(None, min_length=1, max_length=30)
    owner_source: str = Field("Owner-provided", min_length=1, max_length=200)
    actual_monthly_rent: float | None = Field(None, ge=0, le=1e7)

    @model_validator(mode="after")
    def valid_units(self):
        if self.residential_unit_count is not None and (
            self.unit_count is None or self.residential_unit_count > self.unit_count
        ):
            raise ValueError(
                "Residential units must not exceed the supplied total unit count."
            )
        if self.unit_mix:
            expected = (
                self.residential_unit_count
                if self.residential_unit_count is not None
                else self.unit_count
            )
            if expected is None or sum(u.count for u in self.unit_mix) != expected:
                raise ValueError(
                    "Unit mix counts must equal the residential unit count (or total for residential buildings)."
                )
            if (
                self.property_type == "Mixed Use"
                and self.residential_unit_count is None
            ):
                raise ValueError("Mixed-use layouts require a residential unit count.")
        return self

    @field_validator("address")
    @classmethod
    def valid_address(cls, v):
        normalize_address(v)
        return v


class EvaluateRequest(Model):
    addresses: list[PropertyInput | str] = Field(min_length=1, max_length=10)
    assumptions: Assumptions | None = None
    agent: str | None = Field(None, pattern=r"^[a-z0-9-]{1,60}$")

    @field_validator("addresses")
    @classmethod
    def valid_addresses(cls, values):
        result = [PropertyInput(address=x) if isinstance(x, str) else x for x in values]
        keys = [normalize_address(x.address) for x in result]
        if len(set(keys)) != len(keys):
            raise ValueError("Remove duplicate property addresses.")
        if any(p.property_type == "Condo" and p.square_footage is None for p in result):
            raise ValueError("Condo evaluations require owner-provided square footage.")
        return result


class EvaluationContact(Model):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str | None = Field(
        None, min_length=7, max_length=30, pattern=r"^\+?[0-9 ()\-.]+$"
    )


class PublicEvaluateRequest(EvaluateRequest):
    contact: EvaluationContact
    mode: Literal["home", "portfolio"] = "portfolio"

    @model_validator(mode="after")
    def single_home(self):
        if self.mode == "home" and len(self.addresses) != 1:
            raise ValueError("Home evaluations accept exactly one address.")
        return self


class CMARequest(Model):
    estimate_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    owner_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=30, pattern=r"^\+?[0-9 ()\-.]+$")
    expected_value: float | None = Field(None, gt=0, le=1e9)
    note: str = Field("", max_length=2000)
    agent_slug: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
