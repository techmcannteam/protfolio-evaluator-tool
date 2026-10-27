"""Compare providers. Default: committed sanitized fixtures, zero network calls.
Use --live explicitly to call configured providers, respecting Postgres cache/budget.
"""

import argparse
import json
from pathlib import Path

from backend.config import Assumptions, Settings
from backend.models import PropertyInput
from backend.providers.attom import Attom
from backend.providers.base import Transport
from backend.providers.rentcast import RentCast
from backend.repository import Repository
from backend.valuation import calculate

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    fixtures = json.loads((ROOT / "seed/provider_fixtures.json").read_text())
    rows = json.loads((ROOT / "seed/addresses.json").read_text())
    providers = []
    if args.live:
        repo = Repository(settings)
        repo.initialize()
        transport = Transport(repo, settings)
        if settings.rentcast_key:
            providers.append(RentCast(transport, settings.rentcast_key))
        if settings.enable_attom and settings.attom_key:
            providers.append(Attom(transport, settings.attom_key))
        print(
            f"Live maximum before cache: RentCast {30 if settings.rentcast_key else 0}; ATTOM {20 if settings.enable_attom and settings.attom_key else 0}. Per-provider daily cap: {settings.daily_budget}. No HTTP retries."
        )
    else:
        print(
            "Historical cached comparison. Planned provider calls: RentCast 0; ATTOM 0. Not current market data."
        )
    print(
        "| Address | RentCast | ATTOM | Blended | Monthly rent | Cap rate | Sources |"
    )
    print("|---|---:|---:|---:|---:|---:|---|")
    for row in rows:
        sources = (
            [p.evaluate(PropertyInput(**row)) for p in providers]
            if args.live
            else fixtures[row["address"]]
        )
        details = next((x["details"] for x in sources if x.get("details")), {})
        result = calculate(sources, details, Assumptions())

        def money(v):
            return f"${v:,.0f}" if v is not None else "N/A"

        amounts = {
            s["provider"]: (s.get("value") or {}).get("estimate") for s in sources
        }
        value = result["value"] or {}
        rent = result["rent"] or {}
        operating = result["operating"]
        cap = f"{operating['cap_rate'] * 100:.2f}%" if operating else "N/A"
        print(
            "| "
            + " | ".join(
                [
                    row["address"],
                    money(amounts.get("rentcast")),
                    money(amounts.get("attom")),
                    money(value.get("estimate")),
                    money(rent.get("estimate")),
                    cap,
                    ", ".join(value.get("sources", [])),
                ]
            )
            + " |"
        )
    print(
        "\nCap-rate assumptions are placeholders pending Ben. Missing rent means no cap rate. ATTOM results are historical fixtures unless --live is set and ENABLE_ATTOM=true."
    )


if __name__ == "__main__":
    main()
