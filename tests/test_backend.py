import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.config import DISCLAIMER, Assumptions, Settings
from backend.main import create_app
from backend.models import normalize_address
from backend.providers.attom import project as attom_project
from backend.providers.base import Transport
from backend.providers.rentcast import RentCast
from backend.repository import Repository
from backend.valuation import blend, calculate

ADDRESS = "2456 Sepviva St, Philadelphia, PA 19125"
SOURCE = {
    "provider": "rentcast",
    "status": "ok",
    "cached": True,
    "value": {"estimate": 400000, "low": 350000, "high": 450000, "confidence": None},
    "rent": {"estimate": 2500, "low": 2000, "high": 3000},
    "details": {"annual_taxes": 4200},
}


class Provider:
    def evaluate(self, property):
        return SOURCE.copy()


@pytest.fixture
def setup(tmp_path):
    settings = Settings(
        database_url="",
        database_path=str(tmp_path / "test.sqlite3"),
        vercel=False,
        rate_limit=20,
        daily_budget=30,
    )
    repo = Repository(settings)
    with TestClient(create_app(settings, repo, [Provider()])) as client:
        yield client, repo, settings


def test_normalization_units():
    assert normalize_address(
        "219 S 18th Street #902, Philadelphia, PA 19103"
    ) == normalize_address("219 S 18th St Unit 902, Philadelphia, PA 19103")
    assert normalize_address(
        "219 S 18th St Unit 901, Philadelphia, PA 19103"
    ) != normalize_address("219 S 18th St Unit 902, Philadelphia, PA 19103")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Philadelphia",
        "<script>alert(1)</script>",
        "123 Main Street",
        "123 Main St\nPhilly PA 19103",
    ],
)
def test_bad_addresses(value):
    with pytest.raises(ValueError):
        normalize_address(value)


def test_noi():
    result = calculate([SOURCE], SOURCE["details"], Assumptions())
    assert result["operating"]["annual_noi"] == 18400
    assert result["operating"]["cap_rate"] == 0.046
    assert result["operating"]["tax_source"] == "property_record"
    assert calculate([SOURCE], {}, Assumptions())["operating"]["annual_taxes"] == 5600
    assert (
        calculate([SOURCE], {"annual_taxes": 0}, Assumptions())["operating"][
            "annual_taxes"
        ]
        == 0
    )
    assert (
        calculate([SOURCE], {}, Assumptions(annual_taxes=1000))["operating"][
            "annual_taxes"
        ]
        == 1000
    )


def test_blending():
    other = {
        "provider": "attom",
        "value": {
            "estimate": 600000,
            "low": 500000,
            "high": 700000,
            "confidence": 0.95,
        },
    }
    result = blend([SOURCE, other], "value")
    assert result == {
        "estimate": 500000,
        "low": 350000,
        "high": 700000,
        "confidence": "low",
        "sources": ["rentcast", "attom"],
    }
    assert blend([], "value") is None


def test_api_cma(setup):
    client, repo, _ = setup
    assert client.get("/health").status_code == 200
    assert any(
        a["slug"] == "test-ben" for a in client.get("/api/agents").json()["agents"]
    )
    result = client.post(
        "/api/evaluate?agent=test-ben", json={"addresses": [{"address": ADDRESS, "is_rental": True}]}
    ).json()
    assert result["disclaimer"] == DISCLAIMER
    assert result["totals"]["cap_rate"] == 0.046
    assert result["totals"]["complete"]
    identifier = result["properties"][0]["estimate_id"]
    payload = {
        "estimate_id": identifier,
        "owner_name": "Synthetic Test",
        "email": "qa@example.com",
        "phone": "2155550100",
        "agent_slug": "test-ben",
        "expected_value": 500000,
    }
    assert (
        client.post(
            "/api/cma-requests", json={**payload, "our_estimate": 1}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/cma-requests", json={**payload, "agent_slug": "test-nicole"}
        ).status_code
        == 409
    )
    response = client.post("/api/cma-requests", json=payload)
    assert response.status_code == 201 and response.json()["fub"]["sent"] is False
    with repo.transaction() as db:
        row = db.execute("SELECT * FROM cma_requests").fetchone()
        assert row["our_estimate"] == 400000 and row["expected_value"] == 500000
    assert client.get("/api/cma-requests").status_code == 405


def test_validation_and_overrides(setup):
    c, _, _ = setup
    for data in [
        {"addresses": [ADDRESS] * 11},
        {"addresses": [ADDRESS, ADDRESS]},
        {"addresses": [ADDRESS], "assumptions": {"vacancy": 2}},
        {"addresses": ["not an address"]},
    ]:
        assert c.post("/api/evaluate", json=data).status_code == 422
    assert (
        c.post("/api/evaluate?agent=missing", json={"addresses": [ADDRESS]}).json()[
            "agent"
        ]
        == "mike-mccann"
    )
    result = c.post(
        "/api/evaluate",
        json={"addresses": [ADDRESS], "assumptions": {"annual_taxes": 1000}},
    ).json()
    assert result["properties"][0]["operating"]["annual_taxes"] == 1000
    assert result["properties"][0]["assumptions"]["vacancy"] == 0.05


def test_rate_limit_ignores_spoofed_headers(setup):
    c, _, settings = setup
    settings.rate_limit = 1
    assert c.post("/api/evaluate", json={"addresses": [ADDRESS]}).status_code == 200
    response = c.post(
        "/api/evaluate",
        json={"addresses": [ADDRESS]},
        headers={"x-forwarded-for": "1.2.3.4"},
    )
    assert response.status_code == 429 and response.headers["Retry-After"]


def test_concurrent_cache_budget_expiry(setup):
    _, repo, _ = setup

    def claim(_):
        return repo.claim("key", "rentcast", ADDRESS, "value", 1)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(claim, range(5)))
    assert sum(r[0] == "fetch" for r in results) == 1
    token = next(r[2] for r in results if r[0] == "fetch")
    repo.finish("key", token, {"status": "ok", "metric": {}}, 30 * 86400)
    assert claim(0)[0] == "cached"
    assert repo.claim("other", "rentcast", ADDRESS, "rent", 1)[0] == "budget_exhausted"
    with repo.transaction() as db:
        db.execute("UPDATE provider_cache SET expires_at=0 WHERE cache_key=?", ("key",))
    assert repo.claim("key", "rentcast", ADDRESS, "value", 2)[0] == "fetch"


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class HTTP:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/properties"):
            return Response(
                [
                    {
                        "bedrooms": 3,
                        "propertyTaxes": {"2025": {"total": 3200}},
                        "owner": {"name": "do not return"},
                        "school": "do not return",
                    }
                ]
            )
        if "/rent/" in url:
            return Response({"rent": 2400, "rentRangeLow": 2000, "rentRangeHigh": 2800})
        return Response(
            {"price": 400000, "priceRangeLow": 350000, "priceRangeHigh": 450000}
        )


def test_transport_cache_and_whitelist(setup):
    from backend.models import PropertyInput

    _, repo, settings = setup
    http = HTTP()
    provider = RentCast(Transport(repo, settings, http), "test-key")
    first = provider.evaluate(PropertyInput(address=ADDRESS))
    second = provider.evaluate(PropertyInput(address=ADDRESS.replace("St,", "Street,")))
    assert len(http.calls) == 3
    assert second["cached"] and first["details"]["annual_taxes"] == 3200
    assert "owner" not in json.dumps(second) and "school" not in json.dumps(second)


def test_auth_failure_does_not_retry(setup):
    from backend.models import PropertyInput

    _, repo, settings = setup
    http = HTTP()

    def fail(url, **kwargs):
        http.calls.append(url)
        r = Response({})
        r.status_code = 401
        return r

    http.get = fail
    provider = RentCast(Transport(repo, settings, http), "test-key")
    for _ in range(2):
        assert (
            provider.evaluate(PropertyInput(address=ADDRESS))["status"]
            == "provider_auth_error"
        )
    assert len(http.calls) == 1


def test_attom_schema():
    result = attom_project(
        {
            "property": [
                {
                    "avm": {
                        "amount": {
                            "value": 400000,
                            "low": 350000,
                            "high": 450000,
                            "fsd": 0.1,
                            "scr": 90,
                        }
                    }
                }
            ]
        }
    )
    assert result["metric"]["confidence"] == 0.9
    assert attom_project({"property": []})["status"] == "not_found"
    assert (
        attom_project(
            {"property": [{"rentalAvm": {"estimatedRentalValue": 2300}}]}, True
        )["metric"]["estimate"]
        == 2300
    )


def test_missing_rent_does_not_create_zero_cap_rate():
    result = calculate([{**SOURCE, "rent": None}], {}, Assumptions())
    assert result["operating"] is None


def test_vercel_requires_database():
    with pytest.raises(RuntimeError):
        Repository(Settings(database_url="", vercel=True))


def test_partial_portfolio_has_no_aggregate_cap_rate(setup):
    from backend.models import EvaluateRequest
    from backend.service import Evaluator

    _, repo, settings = setup

    class Partial:
        def evaluate(self, property):
            return (
                SOURCE
                if "Sepviva" in property.address
                else {"provider": "rentcast", "status": "not_found", "cached": True}
            )

    result = Evaluator(repo, [Partial()], settings).evaluate(
        EvaluateRequest(addresses=[ADDRESS, "3424 Wallace St, Philadelphia, PA 19104"])
    )
    assert result["totals"]["complete"] is False
    assert result["totals"]["cap_rate"] is None
    assert result["totals"]["properties_valued"] == 1
    assert result["properties"][1]["error"]["code"] == "address_not_found"


def test_ten_historical_property_fixtures():
    from pathlib import Path

    from backend.models import PropertyInput

    fixtures = json.loads(
        (Path(__file__).parents[1] / "seed/provider_fixtures.json").read_text()
    )
    assert len(fixtures) == 10
    for address, sources in fixtures.items():
        PropertyInput(address=address)
        result = calculate(sources, {}, Assumptions())
        assert result["value"]["estimate"] > 0
        assert result["disclaimer"] == DISCLAIMER


def test_fub_stub_never_sends():
    from backend.follow_up_boss import pushToFUB

    assert pushToFUB({"owner_name": "Synthetic QA"}) == {
        "status": "simulated",
        "sent": False,
    }


def test_provider_property_type_disagreement_is_visible(setup):
    from backend.models import PropertyInput

    _, repo, settings = setup
    http = HTTP()
    original = http.get

    def get(url, **kwargs):
        response = original(url, **kwargs)
        if url.endswith("/properties"):
            response.data[0]["propertyType"] = "Condo"
        return response

    http.get = get
    source = RentCast(Transport(repo, settings, http), "test-key").evaluate(
        PropertyInput(address=ADDRESS, property_type="Townhouse")
    )
    assert source["property_type_warning"] and source["match_warning"]
    assert (
        calculate([source], source["details"], Assumptions())["value"]["confidence"]
        == "low"
    )


def test_batch_retains_input_order(setup):
    from backend.models import EvaluateRequest
    from backend.service import Evaluator

    _, repo, settings = setup
    addresses = [ADDRESS, "3424 Wallace St, Philadelphia, PA 19104"]
    result = Evaluator(repo, [Provider()], settings).evaluate(
        EvaluateRequest(addresses=[{"address": a, "is_rental": True} for a in addresses])
    )
    assert [r["address"] for r in result["properties"]] == addresses
    assert result["totals"]["estimated_value"] == 800000
    assert result["totals"]["cap_rate"] == 0.046


@pytest.mark.parametrize(
    "slug", [None, "unknown-agent", "<script>", "a" * 61, "Mike-McCann", "../test-ben"]
)
def test_agent_resolution_falls_back(setup, slug):
    client, _, _ = setup
    response = client.get("/api/agent", params={} if slug is None else {"slug": slug})
    assert response.status_code == 200
    assert response.json()["slug"] == "mike-mccann"
    assert response.json()["full_name"] == "Mike McCann"


def test_roster_profile_and_attribution(setup):
    client, repo, _ = setup
    with repo.transaction() as db:
        db.execute(
            "INSERT INTO agents(slug,name,email,full_name,first_name,title,photo_url,phone,fub_user_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "jane-agent",
                "Jane Agent",
                "jane@example.com",
                "Jane Agent",
                "Jane",
                "McCann Agent",
                "https://example.com/photo.jpg",
                "+12155550100",
                "123",
            ),
        )
    agent = client.get(
        "/api/agent?slug=jane-agent&photo_url=https://evil.example&full_name=Forged"
    ).json()
    assert agent["photo_url"] == "/agents/jane-agent.jpg"
    assert agent["full_name"] == "Jane Agent" and agent["phone"] == "+12155550100"
    assert "fub_user_id" not in agent
    result = client.post(
        "/api/evaluate?agent=jane-agent", json={"addresses": [ADDRESS]}
    ).json()
    identifier = result["properties"][0]["estimate_id"]
    response = client.post(
        "/api/cma-requests",
        json={
            "estimate_id": identifier,
            "owner_name": "QA Owner",
            "email": "qa@example.com",
            "phone": "2155550100",
            "agent_slug": "jane-agent",
        },
    )
    assert response.status_code == 201
    with repo.transaction() as db:
        assert (
            db.execute(
                "SELECT agent_slug FROM cma_requests WHERE id=?",
                (response.json()["id"],),
            ).fetchone()["agent_slug"]
            == "jane-agent"
        )


def test_profile_rejects_unsafe_photo_and_frontend_served(setup):
    client, repo, _ = setup
    with repo.transaction() as db:
        db.execute(
            "UPDATE agents SET photo_url=? WHERE slug=?",
            ("javascript:alert(1)", "test-ben"),
        )
    assert client.get("/api/agent?slug=test-ben").json()["photo_url"] == "/agents/test-ben.jpg"
    assert client.get("/evaluator?agent=test-ben").status_code == 200
    assert client.get("/assets/evaluator.js").status_code == 200
    assert (
        client.get("/?agent=test-ben", follow_redirects=False).headers["location"]
        == "/evaluator?agent=test-ben"
    )


def test_agent_migration_preserves_existing_profiles(setup):
    _, repo, _ = setup
    with repo.transaction() as db:
        db.execute(
            "UPDATE agents SET photo_url=?,phone=? WHERE slug=?",
            ("https://example.com/mike.jpg", "2155550100", "mike-mccann"),
        )
    repo.initialize()
    assert repo.agent("mike-mccann")["photo_url"] == "https://example.com/mike.jpg"


def test_attom_live_scale_and_cached_confidence():
    from backend.models import PropertyInput
    from backend.providers.attom import Attom

    data = {
        "property": [
            {
                "avm": {
                    "amount": {
                        "value": 371211,
                        "low": 337998,
                        "high": 404424,
                        "scr": 91,
                        "fsd": 9,
                    }
                }
            }
        ]
    }
    assert attom_project(data)["metric"]["confidence"] == 0.91
    del data["property"][0]["avm"]["amount"]["scr"]
    assert attom_project(data)["metric"]["confidence"] is None

    class CachedTransport:
        def get(self, *args):
            return {
                "status": "ok",
                "cached": True,
                "metric": {
                    "estimate": 371211,
                    "raw_confidence": 91,
                    "fsd": 9,
                    "confidence": 0,
                },
            }

    result = Attom(CachedTransport(), "test-key").evaluate(
        PropertyInput(address=ADDRESS)
    )
    assert result["cached"] and result["value"]["confidence"] == 0.91


def test_only_rentals_contribute_to_cap_rate(setup):
    client, _, _ = setup
    result = client.post('/api/evaluate', json={'addresses': [
        {'address': ADDRESS, 'property_type': 'Townhouse', 'is_rental': True},
        {'address': '3424 Wallace St, Philadelphia, PA 19104', 'property_type': 'Condo'},
    ]}).json()
    rental, owner = result['properties']
    assert rental['is_rental'] is True
    assert owner['is_rental'] is False
    assert rental['property_type'] == 'Townhouse'
    assert owner['operating']['cap_rate'] is None
    assert result['totals']['cap_rate'] == rental['operating']['cap_rate']
    assert result['totals']['annual_noi'] == rental['operating']['annual_noi']
    result = client.post('/api/evaluate', json={'addresses': [ADDRESS]}).json()
    assert result['totals']['cap_rate'] is None
    assert result['properties'][0]['is_rental'] is False


def test_local_default_agent_photo(setup):
    client, _, _ = setup
    assert client.get('/api/agent').json()['photo_url'] == '/agents/mike-mccann.jpg'
    assert client.get('/agents/mike-mccann.jpg').status_code == 404


def test_record_lookup_reuses_provider_and_does_not_evaluate(setup):
    from fastapi.testclient import TestClient

    from backend.main import create_app
    _, repo, settings = setup

    class RecordProvider:
        def record(self, prop):
            assert prop.address == ADDRESS
            return {'details': {'propertyType': 'Townhouse'}}

        def evaluate(self, prop):
            raise AssertionError('Record lookup must not run valuations')

    with TestClient(create_app(settings, repo, [RecordProvider()])) as client:
        assert client.post('/api/property-record', json={'address': ADDRESS}).json() == {'property_type': 'Townhouse'}
