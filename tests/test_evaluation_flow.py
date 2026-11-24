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
    assert response.json()["delivery"]["team_email"] == "uncertain"
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


def test_default_senders_require_credentials_even_with_flags_enabled(tmp_path):
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
            result["delivery"]["fub"]
            == result["delivery"]["team_email"]
            == "needs_configuration"
        )
        assert client.post(
            f"/api/evaluations/{result['evaluation_id']}/results-shown"
        ).json() == {"owner_email": "needs_configuration"}


def due(repo, identifier, kind):
    with repo.transaction() as db:
        db.execute(
            "UPDATE evaluation_deliveries SET next_attempt_at=0 WHERE evaluation_id=? AND kind=?",
            (identifier, kind),
        )


def test_admin_retry_auth_and_owner_missing_callback(flow):
    client, repo, settings, _, email, _ = flow
    settings.enable_email = True
    settings.delivery_admin_token = "x" * 40
    result = client.post("/api/evaluate", json=request("home")).json()
    identifier = result["evaluation_id"]
    assert client.post("/api/admin/deliveries/retry").status_code == 403
    headers = {"Authorization": "Bearer " + settings.delivery_admin_token}
    assert (
        client.post("/api/admin/deliveries/retry", headers=headers).json()["deliveries"]
        == []
    )
    with repo.transaction() as db:
        db.execute("UPDATE evaluation_leads SET timestamp=0 WHERE id=?", (identifier,))
    due(repo, identifier, "owner_email")
    assert (
        client.post("/api/admin/deliveries/retry", headers=headers).status_code == 200
    )
    assert len(email.messages) == 1
    assert repo.delivery_statuses(identifier)["owner_email"] == "simulated"
    client.post(f"/api/evaluations/{identifier}/results-shown")
    client.post("/api/admin/deliveries/retry", headers=headers)
    assert len(email.messages) == 1


def test_definite_failure_retries_once_and_uncertain_never_retries(flow):
    from backend.delivery_errors import DeliveryError
    from backend.followups import EvaluationFollowups

    client, repo, settings, _, email, _ = flow
    settings.enable_email = settings.enable_team_notifications = True
    original = email.send
    email.send = lambda _: (_ for _ in ()).throw(DeliveryError("smtp_rejected"))
    result = client.post("/api/evaluate", json=request()).json()
    identifier = result["evaluation_id"]
    assert repo.delivery_statuses(identifier)["team_email"] == "failed"
    due(repo, identifier, "team_email")
    email.send = original
    runner = EvaluationFollowups(repo, settings, email_sender=email)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: runner.recover(), range(3)))
    assert len(email.messages) == 1
    assert repo.delivery_statuses(identifier)["team_email"] == "simulated"
    email.send = lambda _: (_ for _ in ()).throw(
        DeliveryError("smtp_acceptance_unknown", "uncertain")
    )
    second = client.post("/api/evaluate", json=request()).json()["evaluation_id"]
    due(repo, second, "team_email")
    email.send = original
    runner.recover()
    assert repo.delivery_statuses(second)["team_email"] == "uncertain"
    assert len(email.messages) == 1


def test_stale_claim_held_and_old_worker_cannot_finalize(flow):
    _, repo, _, _, email, _ = flow
    identifier = repo.save_evaluation_lead(
        {"synthetic": True}, {"team_email": {"from": "", "to": []}}
    )
    claim = repo.claim_delivery(identifier, "team_email")
    with repo.transaction() as db:
        db.execute(
            "UPDATE evaluation_deliveries SET updated_at=0 WHERE evaluation_id=?",
            (identifier,),
        )
    assert repo.recoverable_deliveries() == []
    repo.finish_delivery(identifier, "team_email", "sent", token=claim["_claim_token"])
    assert repo.delivery_statuses(identifier)["team_email"] == "uncertain"
    assert not email.messages


def test_disabled_recovery_never_calls_sender_and_max_attempts_hold(flow):
    from backend.followups import EvaluationFollowups

    client, repo, settings, _, email, events = flow
    identifier = client.post("/api/evaluate", json=request()).json()["evaluation_id"]
    for kind in ["owner_email", "team_email", "fub"]:
        due(repo, identifier, kind)
    runner = EvaluationFollowups(
        repo, settings, email_sender=email, fub_sender=lambda e: events.append(e)
    )
    runner.recover()
    assert not email.messages and not events
    with repo.transaction() as db:
        db.execute(
            "UPDATE evaluation_deliveries SET status='failed',attempts=?,next_attempt_at=0 WHERE evaluation_id=?",
            (settings.delivery_max_attempts, identifier),
        )
    assert repo.recoverable_deliveries() == []


@pytest.mark.parametrize("mode", ["home", "portfolio"])
@pytest.mark.parametrize("agent,expected", [(None, 99), ("test-ben", 52)])
def test_cma_uses_saved_routing_and_mode_and_repeated_submit_is_one_event(
    flow, mode, agent, expected
):
    client, repo, settings, _, _, events = flow
    settings.enable_fub = True
    result = client.post(
        "/api/evaluate" + (f"?agent={agent}" if agent else ""), json=request(mode)
    ).json()
    estimate = result["properties"][0]["estimate_id"]
    body = {
        "estimate_id": estimate,
        "owner_name": "Test Owner",
        "email": "owner@example.com",
        "phone": "2155550100",
        "agent_slug": agent or "mike-mccann",
        "note": "Please prepare a CMA",
    }
    one = client.post("/api/cma-requests", json=body)
    two = client.post("/api/cma-requests", json=body)
    assert one.status_code == two.status_code == 201
    assert one.json()["id"] == two.json()["id"]
    assert len(events) == 2  # one evaluation, one distinct CMA
    event = events[-1]
    assert event["person"]["assignedUserId"] == expected
    assert f"{mode}-evaluation" in event["person"]["tags"]
    assert "cma-request" in event["person"]["tags"]
    assert "Please prepare a CMA" in event["description"]
    assert repo.delivery_statuses(one.json()["id"])["fub"] == "simulated"


def test_generic_fub_waits_for_verified_assignee(flow):
    client, _, settings, _, _, events = flow
    settings.enable_fub = True
    settings.fub_generic_assignee_id = ""
    result = client.post("/api/evaluate", json=request()).json()
    assert result["delivery"]["fub"] == "needs_configuration"
    assert not events


@pytest.mark.parametrize("mode", ["home", "portfolio"])
@pytest.mark.parametrize("agent", [None, "test-ben"])
def test_cma_team_email_uses_saved_context_and_sends_once(flow, mode, agent):
    client, repo, settings, provider, email, events = flow
    result = client.post(
        "/api/evaluate" + (f"?agent={agent}" if agent else ""), json=request(mode)
    ).json()
    calls = provider.calls
    settings.enable_email = settings.enable_team_notifications = True
    settings.internal_notification_recipients = (
        "first@example.com",
        "second@example.com",
    )
    body = {
        "estimate_id": result["properties"][0]["estimate_id"],
        "owner_name": "Test <Owner>",
        "email": "owner@example.com",
        "phone": "2155550100",
        "agent_slug": agent or "mike-mccann",
        "expected_value": 450000,
        "note": "Please <script>alert(1)</script> prepare a CMA",
    }
    one = client.post("/api/cma-requests", json=body)
    two = client.post("/api/cma-requests", json=body)
    assert one.status_code == two.status_code == 201
    assert one.json()["id"] == two.json()["id"]
    assert len(email.messages) == 1
    message = email.messages[0]
    assert message["to"] == ["first@example.com", "second@example.com"]
    assert message["from"] == "results@example.com"
    assert message["subject"] == f"New McCann {mode} CMA request"
    assert message["delivery_id"] == one.json()["id"] + ":team_email"
    for content in (message["text"], message["html"]):
        assert ADDRESS in content
        assert "owner@example.com" in content and "2155550100" in content
        assert "$400,000" in content
        assert f"/evaluator/{mode}" + ("?agent=test-ben" if agent else "") in content
        assert ("agent_link" if agent else "generic_link") in content
        assert "?agent=mike-mccann" not in content
    assert "$450,000" in message["html"]
    assert "Test &lt;Owner&gt;" in message["html"]
    assert "&lt;script&gt;" in message["html"] and "<script>" not in message["html"]
    assert repo.delivery_statuses(one.json()["id"]) == {
        "fub": "disabled",
        "team_email": "simulated",
    }
    assert provider.calls == calls and not events


@pytest.mark.parametrize(
    "email_on,team_on", [(False, False), (True, False), (False, True)]
)
def test_cma_team_email_stays_saved_but_disabled_behind_both_flags(
    flow, email_on, team_on
):
    client, repo, settings, _, email, events = flow
    result = client.post("/api/evaluate", json=request()).json()
    settings.enable_email, settings.enable_team_notifications = email_on, team_on
    response = client.post(
        "/api/cma-requests",
        json={
            "estimate_id": result["properties"][0]["estimate_id"],
            "owner_name": "Test Owner",
            "email": "owner@example.com",
            "note": "CMA please",
            "agent_slug": "mike-mccann",
            "phone": "2155550100",
        },
    )
    assert response.status_code == 201
    assert repo.delivery_statuses(response.json()["id"]) == {
        "fub": "disabled",
        "team_email": "disabled",
    }
    assert not email.messages and not events


def test_cma_team_email_failed_delivery_recovers_without_duplicate_or_provider_call(
    flow,
):
    from backend.delivery_errors import DeliveryError
    from backend.followups import EvaluationFollowups

    client, repo, settings, provider, email, events = flow
    result = client.post("/api/evaluate", json=request()).json()
    calls = provider.calls
    settings.enable_email = settings.enable_team_notifications = True
    original = email.send
    email.send = lambda _: (_ for _ in ()).throw(DeliveryError("smtp_rejected"))
    response = client.post(
        "/api/cma-requests",
        json={
            "estimate_id": result["properties"][0]["estimate_id"],
            "owner_name": "Test Owner",
            "email": "owner@example.com",
            "note": "CMA please",
            "agent_slug": "mike-mccann",
            "phone": "2155550100",
        },
    )
    identifier = response.json()["id"]
    assert repo.delivery_statuses(identifier)["team_email"] == "failed"
    due(repo, identifier, "team_email")
    email.send = original
    runner = EvaluationFollowups(repo, settings, email_sender=email)
    runner.dispatch(identifier, "team_email", retry=True)
    runner.dispatch(identifier, "team_email", retry=True)
    assert repo.delivery_statuses(identifier)["team_email"] == "simulated"
    assert len(email.messages) == 1
    assert email.messages[0]["delivery_id"] == identifier + ":team_email"
    assert provider.calls == calls and not events


def test_legacy_outbox_payload_gets_stable_delivery_id_and_respects_grace_period(flow):
    from backend.followups import EvaluationFollowups

    client, repo, settings, _, email, _ = flow
    settings.enable_email = True
    identifier = client.post("/api/evaluate", json=request()).json()["evaluation_id"]
    with repo.transaction() as db:
        row = db.execute(
            "SELECT payload FROM evaluation_deliveries WHERE evaluation_id=? AND kind='owner_email'",
            (identifier,),
        ).fetchone()
        legacy = json.loads(row["payload"])
        legacy.pop("delivery_id")
        legacy.pop("created_at")
        db.execute(
            "UPDATE evaluation_deliveries SET payload=?,next_attempt_at=0 WHERE evaluation_id=? AND kind='owner_email'",
            (json.dumps(legacy), identifier),
        )
    runner = EvaluationFollowups(repo, settings, email_sender=email)
    runner.recover()
    assert not email.messages
    with repo.transaction() as db:
        db.execute("UPDATE evaluation_leads SET timestamp=0 WHERE id=?", (identifier,))
    runner.recover()
    assert email.messages[0]["delivery_id"] == f"{identifier}:owner_email"
    assert email.messages[0]["created_at"] == 0


def test_per_unit_expenses_from_owner_count_and_unknown_count_review(flow):
    client, _, settings, _, _, _ = flow
    from backend.config import Assumptions

    settings.defaults = Assumptions(
        maintenance_mode="per_unit",
        maintenance_per_unit=600,
        insurance_mode="per_unit",
        insurance_per_unit=400,
    )
    data = request()
    data["addresses"][0]["unit_count"] = 3
    result = client.post("/api/evaluate", json=data).json()["properties"][0]
    assert result["operating"]["annual_maintenance"] == 1800
    assert result["operating"]["annual_insurance"] == 1200
    assert result["expense_unit_count"] == 3
    missing = client.post("/api/evaluate", json=request()).json()
    assert missing["properties"][0]["operating"] is None
    assert missing["totals"]["cap_rate"] is None
    assert missing["properties"][0]["expense_status"] == "needs_unit_count"
