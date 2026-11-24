"""Local browser-test server: synthetic roster/provider, never uses real credentials."""

import os
from pathlib import Path

from backend.config import Settings
from backend.main import create_app
from backend.repository import Repository

settings = Settings(
    database_url="",
    database_path=os.environ["BROWSER_TEST_DB"],
    vercel=False,
    rate_limit=10000,
    roster_path=str(Path(__file__).parent / "fixtures/agent-roster.json"),
)
repo = Repository(settings)
repo.initialize()
with repo.transaction() as db:
    for slug, photo in [
        ("jane-agent", "/assets/interior.jpg"),
        ("broken-agent", "/assets/missing-photo.jpg"),
        ("no-photo", ""),
    ]:
        db.execute(
            "INSERT INTO agents(slug,name,email,full_name,first_name,title,photo_url,phone) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(slug) DO NOTHING",
            (
                slug,
                "Jane Agent",
                "jane@example.com",
                "Jane Agent",
                "Jane",
                "The Mike McCann Team · Keller Williams",
                photo,
                "+12155550100",
            ),
        )


class Provider:
    def record(self, prop):
        return {"status": "ok", "details": {"propertyType": "Condo" if "219" in prop.address else "Townhouse"}}

    def evaluate(self, prop):
        if prop.unit_count:
            from backend.providers.rentcast import RentCast

            class MultiTransport:
                def get(self, provider, address, url, params, headers, project):
                    subject = {"formattedAddress": prop.address, "propertyType": "Multi-Family"}
                    if url.endswith("/properties"):
                        data = [{**subject, "features": {"unitCount": prop.unit_count}}]
                    elif url.endswith("/value"):
                        data = {"price": 800000, "priceRangeLow": 750000, "priceRangeHigh": 900000, "subjectProperty": subject}
                    else:
                        rent = 1000 if params["bedrooms"] == 0 else 2000
                        data = {"rent": rent, "rentRangeLow": rent - 100, "rentRangeHigh": rent + 200}
                    return {**project(data), "cached": True}

            return RentCast(MultiTransport(), "synthetic").evaluate(prop)
        if "999" in prop.address:
            return {"provider": "test", "status": "not_found", "cached": True}
        return {
            "provider": "test",
            "status": "ok",
            "cached": True,
            "value": {
                "estimate": 480000,
                "low": 455000,
                "high": 505000,
                "confidence": 0.9,
            },
            "rent": {"estimate": 2850, "low": 2600, "high": 3000},
            "details": {
                "bedrooms": 3,
                "bathrooms": 2,
                "squareFootage": 1480,
                "annual_taxes": 5000,
            },
        }


app = create_app(settings, repo, [Provider()])
