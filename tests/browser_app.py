"""Local browser-test server: synthetic roster/provider, never uses real credentials."""

import os

from backend.config import Settings
from backend.main import create_app
from backend.repository import Repository

settings = Settings(
    database_url="",
    database_path=os.environ["BROWSER_TEST_DB"],
    vercel=False,
    rate_limit=10000,
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
