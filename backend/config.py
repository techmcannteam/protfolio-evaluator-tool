"""All operating assumptions are placeholders pending Ben's confirmation."""

import os
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

DISCLAIMER = "Estimates are automated and not an appraisal. Ask your agent for a CMA."


class Assumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    vacancy: float = Field(0.05, ge=0, le=1)
    management: float = Field(0.08, ge=0, le=1)
    maintenance: float = Field(0.05, ge=0, le=1)
    insurance_rate: float = Field(0.005, ge=0, le=0.2)
    fallback_tax_rate: float = Field(0.014, ge=0, le=0.2)
    annual_taxes: float | None = Field(None, ge=0, le=1e8)


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", ""), repr=False
    )
    database_path: str = field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "evaluator.sqlite3")
    )
    rentcast_key: str = field(
        default_factory=lambda: os.getenv("RENTCAST_API_KEY", ""), repr=False
    )
    attom_key: str = field(
        default_factory=lambda: os.getenv("ATTOM_API_KEY", ""), repr=False
    )
    google_places_key: str = field(
        default_factory=lambda: os.getenv("GOOGLE_PLACES_API_KEY", ""), repr=False
    )
    enable_attom: bool = field(
        default_factory=lambda: os.getenv("ENABLE_ATTOM", "false").lower() == "true"
    )
    enable_fub: bool = field(
        default_factory=lambda: os.getenv("ENABLE_FUB", "false").lower() == "true"
    )
    rate_limit: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_HOUR", "20"))
    )
    daily_budget: int = field(
        default_factory=lambda: int(os.getenv("PROVIDER_DAILY_CALL_LIMIT", "30"))
    )
    ip_salt: str = field(
        default_factory=lambda: os.getenv("IP_HASH_SALT", "local-development-only"),
        repr=False,
    )
    vercel: bool = field(default_factory=lambda: bool(os.getenv("VERCEL")))
    defaults: Assumptions = field(
        default_factory=lambda: Assumptions(
            **{
                k: float(os.environ["DEFAULT_" + k.upper()])
                for k in [
                    "vacancy",
                    "management",
                    "maintenance",
                    "insurance_rate",
                    "fallback_tax_rate",
                ]
                if "DEFAULT_" + k.upper() in os.environ
            }
        )
    )
