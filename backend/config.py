"""All operating assumptions are placeholders pending Ben's confirmation."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DISCLAIMER = "Estimates are automated and not an appraisal. Ask your agent for a CMA."
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
EXPENSE_DEFAULTS = json.loads((CONFIG_DIR / "expense-assumptions.json").read_text())


class Assumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    vacancy: float = Field(EXPENSE_DEFAULTS["vacancy"], ge=0, le=1)
    management: float = Field(EXPENSE_DEFAULTS["management"], ge=0, le=1)
    maintenance: float = Field(EXPENSE_DEFAULTS["maintenance"], ge=0, le=1)
    maintenance_mode: Literal["percent_rent", "per_unit"] = EXPENSE_DEFAULTS[
        "maintenance_mode"
    ]
    maintenance_per_unit: float = Field(
        EXPENSE_DEFAULTS["maintenance_per_unit"], ge=0, le=1e6
    )
    insurance_rate: float = Field(EXPENSE_DEFAULTS["insurance_rate"], ge=0, le=0.2)
    insurance_mode: Literal["percent_value", "percent_rent", "per_unit"] = (
        EXPENSE_DEFAULTS["insurance_mode"]
    )
    insurance_rent_rate: float = Field(
        EXPENSE_DEFAULTS["insurance_rent_rate"], ge=0, le=1
    )
    insurance_per_unit: float = Field(
        EXPENSE_DEFAULTS["insurance_per_unit"], ge=0, le=1e6
    )
    fallback_tax_rate: float = Field(
        EXPENSE_DEFAULTS["fallback_tax_rate"], ge=0, le=0.2
    )
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
    fub_api_key: str = field(
        default_factory=lambda: os.getenv("FUB_API_KEY", ""), repr=False
    )
    fub_system: str = field(default_factory=lambda: os.getenv("FUB_SYSTEM", ""))
    fub_system_key: str = field(
        default_factory=lambda: os.getenv("FUB_SYSTEM_KEY", ""), repr=False
    )
    enable_email: bool = field(
        default_factory=lambda: os.getenv("ENABLE_EMAIL", "false").lower() == "true"
    )
    enable_team_notifications: bool = field(
        default_factory=lambda: (
            os.getenv("ENABLE_TEAM_NOTIFICATIONS", "false").lower() == "true"
        )
    )
    email_from: str = field(default_factory=lambda: os.getenv("EMAIL_FROM", ""))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_security: str = field(
        default_factory=lambda: os.getenv("SMTP_SECURITY", "starttls")
    )
    smtp_username: str = field(
        default_factory=lambda: os.getenv("SMTP_USERNAME", ""), repr=False
    )
    smtp_password: str = field(
        default_factory=lambda: os.getenv("SMTP_PASSWORD", ""), repr=False
    )
    delivery_admin_token: str = field(
        default_factory=lambda: os.getenv("DELIVERY_ADMIN_TOKEN", ""), repr=False
    )
    owner_email_delay_seconds: int = field(
        default_factory=lambda: int(os.getenv("OWNER_EMAIL_DELAY_SECONDS", "900"))
    )
    delivery_retry_seconds: int = field(
        default_factory=lambda: int(os.getenv("DELIVERY_RETRY_SECONDS", "300"))
    )
    delivery_max_attempts: int = field(
        default_factory=lambda: int(os.getenv("DELIVERY_MAX_ATTEMPTS", "5"))
    )
    roster_path: str = field(
        default_factory=lambda: os.getenv(
            "AGENT_ROSTER_PATH", str(CONFIG_DIR / "agent-roster.json")
        )
    )
    internal_notification_recipients: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            x.strip()
            for x in os.getenv("INTERNAL_NOTIFICATION_RECIPIENTS", "").split(",")
            if x.strip()
        )
    )
    fub_generic_assignee_id: str = field(
        default_factory=lambda: os.getenv("FUB_GENERIC_ASSIGNEE_ID", "")
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
                },
                **json.loads(os.getenv("EXPENSE_ASSUMPTIONS_JSON", "{}")),
            }
        )
    )
