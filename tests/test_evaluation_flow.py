import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.config import DISCLAIMER, Settings
from backend.followups import resolve_routing
from backend.main import create_app
from backend.presentation import condition_display
from backend.repository import Repository

ADDRESS = "100 Example St, Philadelphia, PA 19103"
CONTACT = {"name": "Synthetic Owner", "email": "owner@example.com"}
VALUE = {"estimate": 400000, "low": 300000, "high": 500000}


class SyntheticProvider:
    calls = 0

    def evaluate(self, property):
        self.calls += 1
        return {
            "provider": "rentcast",
            "status": "ok",
            "cached": True,
            "value": copy.deepcopy(VALUE),
            "rent": {"estimate": 2500, "low": 2000, "high": 3000},
            "details": {},
        }


class RecordingEmail:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(copy.deepcopy(message))
        return {"status": "simulated", "sent": False}


@pytest.fixture
def flow(tmp_path):
    settings = Settings(
        database_url="",
        database_path=str(tmp_path / "leads.db"),
        vercel=False,
        rate_limit=100,
        enable_attom=False,
        enable_fub=False,
        enable_email=False,
        enable_team_notifications=False,
        email_from="results@example.com",
        internal_notification_recipients=("team@example.com",),
        fub_generic_assignee_id="99",
    )
    repo = Repository(settings)
    repo.initialize()
    with repo.transaction() as db:
        db.execute("UPDATE agents SET fub_user_id='52' WHERE slug='test-ben'")
        db.execute("UPDATE agents SET fub_user_id='10' WHERE slug='mike-mccann'")
    provider, email, events = SyntheticProvider(), RecordingEmail(), []

    def fub(event):
        events.append(copy.deepcopy(event))
        return {"status": "simulated", "sent": False}

    with TestClient(create_app(settings, repo, [provider], email, fub)) as client:
        yield client, repo, settings, provider, email, events


def request(mode="portfolio", updated=None):
    return {
        "addresses": [
            {"address": ADDRESS, "is_rental": True, "recently_updated": updated}
        ],
        "contact": CONTACT,
        "mode": mode,
    }


def saved(repo, identifier):
    with repo.transaction() as db:
        return json.loads(
            db.execute(
                "SELECT payload FROM evaluation_leads WHERE id=?", (identifier,)
            ).fetchone()["payload"]
        )


@pytest.mark.parametrize("mode", ["home", "portfolio"])
@pytest.mark.parametrize(
    "slug,assignee,kind",
    [
        (None, 99, "generic_link"),
        ("test-ben", 52, "agent_link"),
        ("mike-mccann", 10, "agent_link"),
        ("unknown", 99, "generic_link"),
    ],
)
def test_link_routing_and_fub_events_shape(flow, mode, slug, assignee, kind):
    client, repo, settings, _, _, events = flow
    settings.enable_fub = True  # injected stub only
    data = request(mode)
    data["contact"] = {**CONTACT, "phone": "2155550100"}
    result = client.post(
        "/api/evaluate" + (f"?agent={slug}" if slug else ""), json=data
    ).json()
    lead = saved(repo, result["evaluation_id"])
    assert (
        lead["routing"]["kind"] == kind and lead["routing"]["assignee_id"] == assignee
    )
    assert result["delivery"]["fub"] == "simulated"
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "Seller Inquiry"
    assert event["source"] == f"McCann {mode.title()} Evaluation"
    assert event["person"]["assignedUserId"] == assignee
    assert event["person"]["emails"] == [{"value": CONTACT["email"]}]
    assert event["person"]["phones"] == [{"value": "2155550100"}]
    assert f"{mode}-evaluation" in event["person"]["tags"]
    assert ADDRESS in event["description"] and "$400,000" in event["description"]
    assert "assignee_id" not in result and "contact" not in result


def test_generic_assignee_config_and_missing_agent_mapping_never_fall_back(flow):
    _, repo, settings, _, _, _ = flow
    settings.fub_generic_assignee_id = "123"
    assert resolve_routing(repo, settings, None)["assignee_id"] == 123
    assert resolve_routing(repo, settings, "test-nicole")["assignee_id"] is None
    assert resolve_routing(repo, settings, "test-nicole")["kind"] == "agent_link"
    settings.fub_generic_assignee_id = ""
    assert resolve_routing(repo, settings, None)["status"] == "needs_configuration"


def test_all_disabled_flags_prevent_stub_invocation_but_persist_every_evaluation(flow):
    client, repo, _, _, email, events = flow
    result = client.post("/api/evaluate", json=request()).json()
    identifier = result["evaluation_id"]
    assert result["delivery"] == {
        "fub": "disabled",
        "team_email": "disabled",
        "owner_email": "waiting_for_results",
    }
    assert saved(repo, identifier)["contact"] == {**CONTACT, "phone": None}
    response = client.post(f"/api/evaluations/{identifier}/results-shown")
    assert response.json() == {"owner_email": "disabled"}
    assert email.messages == [] and events == []


def test_owner_email_waits_for_results_and_is_idempotent_team_has_context(flow):
    client, repo, settings, _, email, _ = flow
    settings.enable_email = settings.enable_team_notifications = True
    data = request(updated=True)
    data["addresses"].append({"address": ADDRESS.replace("100", "101")})
    result = client.post("/api/evaluate?agent=test-ben", json=data).json()
    identifier = result["evaluation_id"]
    assert len(email.messages) == 1
    team = email.messages[0]
    assert team["to"] == ["team@example.com"]
    assert all(
        s in team["text"]
        for s in [
            CONTACT["name"],
            CONTACT["email"],
            "Phone: Not provided",
            "/evaluator/portfolio?agent=test-ben",
            ADDRESS,
            "101 Example",
            "$460,000",
            "Cap rate:",
        ]
    )
    assert repo.delivery_statuses(identifier)["owner_email"] == "waiting_for_results"
    for _ in range(2):
        assert client.post(f"/api/evaluations/{identifier}/results-shown").json() == {
            "owner_email": "simulated"
        }
    assert len(email.messages) == 2
    owner = email.messages[1]
    assert owner["from"] == "results@example.com" and owner["to"] == [CONTACT["email"]]
    assert (
        ADDRESS in owner["text"]
        and "$460,000" in owner["text"]
        and DISCLAIMER in owner["text"]
    )
    assert "team@example.com" not in owner["text"]


def test_no_notifications_for_empty_recipients_and_no_fub_without_assignee(flow):
    client, _, settings, _, email, events = flow
    settings.enable_email = settings.enable_team_notifications = settings.enable_fub = (
        True
    )
    settings.internal_notification_recipients = ()
    settings.fub_generic_assignee_id = ""
    result = client.post("/api/evaluate", json=request()).json()
    assert (
        result["delivery"]["team_email"]
        == result["delivery"]["fub"]
        == "needs_configuration"
    )
    assert email.messages == [] and events == []


@pytest.mark.parametrize("mode", ["home", "portfolio"])
@pytest.mark.parametrize("missing_value", [False, True])
def test_email_cap_labels_and_paragraph_spacing(flow, mode, missing_value):
    client, _, settings, provider, email, _ = flow
    settings.enable_email = settings.enable_team_notifications = True
    if missing_value:
        provider.evaluate = lambda p: {
            "provider": "rentcast",
            "status": "not_found",
            "cached": True,
        }
    result = client.post("/api/evaluate?agent=test-ben", json=request(mode)).json()
    client.post(f"/api/evaluations/{result['evaluation_id']}/results-shown")
    assert len(email.messages) == 2
    for message in email.messages:
        text = message["text"]
        html = message["html"]
        cap_label = "Cap rate" if mode == "home" else "Portfolio cap rate"
        cap = result["totals"]["cap_rate"]
        expected = f"{cap:.2%}" if cap is not None else "Unavailable"
        assert f"\n{cap_label}: {expected}\n\n" in text
        assert f"{cap_label}</th>" in html
        assert expected in html
        assert DISCLAIMER in html
        assert "Most likely" in html and "Condition guide" in html
        if mode == "home":
            assert "Portfolio cap rate" not in text
            assert "Portfolio cap rate" not in html
        assert f"{ADDRESS}\n\nMost likely:" in text
        assert "\n\nProvider estimate:" in text
        assert f"\n\n{DISCLAIMER}" in text
        assert "\n\n\n" not in text
    assert "Phone: Not provided\n\nAgent link:" in email.messages[0]["text"]
    assert email.messages[1]["text"].startswith(f"Hello {CONTACT['name']},\n\n")
    assert "Owner details" in email.messages[0]["html"]
    assert "Owner details" not in email.messages[1]["html"]


def test_email_html_escapes_owner_input_and_keeps_internal_details_private(flow):
    client, _, settings, _, email, _ = flow
    settings.enable_email = settings.enable_team_notifications = True
    data = request("home")
    data["contact"] = {**CONTACT, "name": '<img src=x onerror="alert(1)">'}
    result = client.post("/api/evaluate?agent=test-ben", json=data).json()
    client.post(f"/api/evaluations/{result['evaluation_id']}/results-shown")
    for message in email.messages:
        assert "<img" not in message["html"]
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in message["html"]
    assert "/evaluator/home?agent=test-ben" in email.messages[0]["html"]
    assert "agent_link" not in email.messages[1]["html"]
    assert "team@example.com" not in email.messages[1]["html"]


def test_not_found_still_records_internal_notification(flow):
    client, _, settings, provider, email, _ = flow
    settings.enable_email = settings.enable_team_notifications = True
    provider.evaluate = lambda p: {
        "provider": "rentcast",
        "status": "not_found",
        "cached": True,
    }
    result = client.post("/api/evaluate", json=request()).json()
    assert result["properties"][0]["value"] is None
    assert len(email.messages) == 1 and "Unavailable" in email.messages[0]["text"]


def test_delivery_failure_does_not_fail_evaluation_or_leak_contact(flow):
    client, _, settings, _, email, _ = flow
    settings.enable_email = settings.enable_team_notifications = True

    def fail(message):
        raise RuntimeError("private data must not be echoed")

    email.send = fail
    response = client.post("/api/evaluate", json=request())
    assert response.status_code == 200
    assert response.json()["delivery"]["team_email"] == "failed"
    assert "private data" not in response.text


@pytest.mark.parametrize(
    "contact",
    [
        None,
        {},
        {"name": "A", "email": "a@example.com"},
        {"name": "Owner", "email": "invalid"},
        {**CONTACT, "phone": "bad"},
    ],
)
def test_contact_required_before_evaluation(flow, contact):
    client, repo, _, provider, _, _ = flow
    data = request()
    if contact is None:
        del data["contact"]
    else:
        data["contact"] = contact
    assert client.post("/api/evaluate", json=data).status_code == 422
    assert provider.calls == 0
    with repo.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM evaluation_leads").fetchone()[0] == 0


def test_home_one_address_api_limit_and_both_routes(flow):
    client, _, _, provider, _, _ = flow
    for path in ["/evaluator/home", "/evaluator/portfolio", "/evaluator"]:
        assert client.get(path + "?agent=test-ben").status_code == 200
    data = request("home")
    data["addresses"].append({"address": ADDRESS.replace("100", "101")})
    assert client.post("/api/evaluate", json=data).status_code == 422
    assert provider.calls == 0


@pytest.mark.parametrize(
    "updated,indicated", [(None, 400000), (False, 400000), (True, 460000)]
)
def test_condition_changes_only_display_value(flow, updated, indicated):
    client, _, _, _, _, _ = flow
    original = client.post("/api/evaluate", json=request()).json()
    adjusted = client.post("/api/evaluate", json=request(updated=updated)).json()
    a, b = original["properties"][0], adjusted["properties"][0]
    for field in ["value", "rent", "operating", "sources"]:
        assert a[field] == b[field]
    assert original["totals"] == adjusted["totals"]
    assert b["display_value"]["most_likely"] == indicated
    assert b["display_value"]["low"] == 300000 and b["display_value"]["high"] == 500000
    assert adjusted["disclaimer"] == DISCLAIMER


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"estimate": 400000, "low": None, "high": 500000},
        {"estimate": 400000, "low": 400000, "high": 400000},
        {"estimate": 490000, "low": 300000, "high": 500000},
    ],
)
def test_condition_missing_range_and_high_estimate_stay_safe(value):
    original = copy.deepcopy(value)
    result = condition_display(value, True)
    assert value == original
    assert (
        result is None if value is None else result["most_likely"] == value["estimate"]
    )


def test_atomic_delivery_claim(flow):
    client, repo, _, _, _, _ = flow
    identifier = client.post("/api/evaluate", json=request()).json()["evaluation_id"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        claims = list(
            pool.map(
                lambda _: repo.claim_delivery(identifier, "owner_email", True), range(3)
            )
        )
    assert sum(c is not None for c in claims) == 1


def test_default_senders_never_send_even_with_flags_enabled(tmp_path):
    settings = Settings(
        database_url="",
        database_path=str(tmp_path / "stub.db"),
        vercel=False,
        enable_email=True,
        enable_team_notifications=True,
        enable_fub=True,
        email_from="results@example.com",
        internal_notification_recipients=("team@example.com",),
        fub_generic_assignee_id="99",
    )
    with TestClient(create_app(settings, providers=[SyntheticProvider()])) as client:
        result = client.post("/api/evaluate", json=request()).json()
        assert (
            result["delivery"]["fub"] == result["delivery"]["team_email"] == "simulated"
        )
        assert client.post(
            f"/api/evaluations/{result['evaluation_id']}/results-shown"
        ).json() == {"owner_email": "simulated"}
