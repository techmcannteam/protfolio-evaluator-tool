"""Initialize only the evaluator schema and verify persistent behavior."""

import uuid

from dotenv import load_dotenv

from backend.config import Settings
from backend.models import CMARequest
from backend.repository import Repository

load_dotenv()
settings = Settings()
assert settings.database_url, "DATABASE_URL required"
repo = Repository(settings)
repo.initialize()
prefix = "smoke:" + str(uuid.uuid4())
assert repo.consume(prefix, 1)
assert not repo.consume(prefix, 1)
result = repo.claim(prefix, "smoke", "Synthetic verification", "test", 1)
assert result[0] == "fetch"
repo.finish(prefix, result[2], {"status": "ok", "value": 1}, 60)
assert repo.claim(prefix, "smoke", "Synthetic verification", "test", 1)[0] == "cached"
identifier = repo.save_estimate(
    "Synthetic verification", "test-ben", {"value": {"estimate": 400000}}
)
cma_id = repo.save_cma(
    CMARequest(
        estimate_id=identifier,
        owner_name="Synthetic QA",
        email="qa@example.com",
        phone="2155550100",
        agent_slug="test-ben",
    ),
    repo.estimate(identifier),
    "simulated",
)
with repo.transaction() as db:
    assert (
        db.execute(
            "SELECT our_estimate FROM cma_requests WHERE id=?", (cma_id,)
        ).fetchone()["our_estimate"]
        == 400000
    )
    db.execute("DELETE FROM cma_requests WHERE id=?", (cma_id,))
    db.execute("DELETE FROM estimates WHERE id=?", (identifier,))
    db.execute("DELETE FROM provider_cache WHERE cache_key=?", (prefix,))
    db.execute("DELETE FROM provider_calls WHERE provider=?", ("smoke",))
    db.execute("DELETE FROM counters WHERE counter_key=?", (prefix,))
print(
    "Neon schema, cache, budget, estimates and CMA persistence passed. Synthetic contact rows removed. No permit tables accessed."
)
