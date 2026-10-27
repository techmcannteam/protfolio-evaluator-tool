import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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


class PropertyInput(Model):
    is_rental: bool = False
    address: str = Field(min_length=10, max_length=250)
    property_type: (
        Literal[
            "Single Family",
            "Townhouse",
            "Condo",
            "Multi-Family",
            "Apartment",
            "Manufactured",
        ]
        | None
    ) = None

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
        return result


class CMARequest(Model):
    estimate_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    owner_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=30, pattern=r"^\+?[0-9 ()\-.]+$")
    expected_value: float | None = Field(None, gt=0, le=1e9)
    note: str = Field("", max_length=2000)
    agent_slug: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
