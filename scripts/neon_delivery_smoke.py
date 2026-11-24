"""Explicitly authorized, synthetic outbox check confined to portfolio_evaluator.

Run with PREVIEW_DATABASE_URL set. No providers, FUB or email senders are invoked.
The caller must verify that the connection points to an authorized test database.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from backend.config import Settings
from backend.repository import Repository


def exercise(repo):
    identifiers = []
    cleaned = False
    try:
        identifier = repo.save_evaluation_lead(
            {
                "kind": "synthetic_delivery_smoke",
                "contact": {"name": "Synthetic QA", "email": "qa@example.com"},
            },
            {
                kind: {"synthetic": True}
                for kind in ("fub", "team_email", "owner_email")
            },
        )
        identifiers.append(identifier)
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(
                pool.map(lambda _: repo.claim_delivery(identifier, "fub"), range(4))
            )
        winners = [claim for claim in claims if claim]
        assert len(winners) == 1
        claim = winners[0]
        assert repo.begin_delivery_attempt(identifier, "fub", claim)
        repo.finish_delivery(
            identifier, "fub", "simulated", token=claim["_claim_token"]
        )
        assert repo.claim_delivery(identifier, "fub", retry=True) is None

        claim = repo.claim_delivery(identifier, "team_email")
        assert repo.begin_delivery_attempt(identifier, "team_email", claim)
        repo.finish_delivery(
            identifier,
            "team_email",
            "failed",
            token=claim["_claim_token"],
            error="synthetic_rejection",
        )
        retry = repo.claim_delivery(identifier, "team_email", retry=True)
        assert retry and retry["delivery_id"] == claim["delivery_id"]
        assert repo.begin_delivery_attempt(identifier, "team_email", retry)
        repo.finish_delivery(
            identifier, "team_email", "simulated", token=retry["_claim_token"]
        )

        # No results-shown callback: the overdue outbox entry can still be claimed.
        owner = repo.claim_delivery(identifier, "owner_email", retry=True)
        assert owner
        assert repo.begin_delivery_attempt(identifier, "owner_email", owner)
        repo.finish_delivery(
            identifier, "owner_email", "simulated", token=owner["_claim_token"]
        )
        assert (
            repo.claim_delivery(identifier, "owner_email", results_shown=True) is None
        )
        assert repo.delivery_statuses(identifier) == {
            "fub": "simulated",
            "team_email": "simulated",
            "owner_email": "simulated",
        }
        with repo.transaction() as db:
            rows = db.execute(
                "SELECT kind,attempts FROM evaluation_deliveries WHERE evaluation_id=?",
                (identifier,),
            ).fetchall()
            assert {r["kind"]: r["attempts"] for r in rows} == {
                "fub": 1,
                "team_email": 2,
                "owner_email": 1,
            }
    finally:
        with repo.transaction() as db:
            for identifier in identifiers:
                db.execute(
                    "DELETE FROM evaluation_deliveries WHERE evaluation_id=?",
                    (identifier,),
                )
                db.execute("DELETE FROM evaluation_leads WHERE id=?", (identifier,))
        with repo.transaction() as db:
            for identifier in identifiers:
                assert (
                    db.execute(
                        "SELECT count(*) AS n FROM evaluation_deliveries WHERE evaluation_id=?",
                        (identifier,),
                    ).fetchone()["n"]
                    == 0
                )
                assert (
                    db.execute(
                        "SELECT count(*) AS n FROM evaluation_leads WHERE id=?",
                        (identifier,),
                    ).fetchone()["n"]
                    == 0
                )
        cleaned = True
    return {
        "database": "postgres" if repo.postgres else "sqlite",
        "concurrent_claim": "passed",
        "failed_retry": "passed",
        "missing_callback": "passed",
        "duplicate_prevention": "passed",
        "synthetic_rows_removed": cleaned,
        "provider_calls": 0,
        "fub_writes": 0,
        "emails_sent": 0,
    }


def main():
    url = os.environ.get("PREVIEW_DATABASE_URL", "")
    if not url or not (urlparse(url).hostname or "").endswith(".neon.tech"):
        raise SystemExit(
            "An explicitly authorized Neon PREVIEW_DATABASE_URL is required."
        )
    repo = Repository(
        Settings(
            database_url=url,
            vercel=False,
            enable_attom=False,
            enable_fub=False,
            enable_email=False,
            enable_team_notifications=False,
            owner_email_delay_seconds=0,
            delivery_retry_seconds=0,
        )
    )
    repo.initialize(seed_roster=False)
    print(json.dumps(exercise(repo), indent=2))


if __name__ == "__main__":
    main()
