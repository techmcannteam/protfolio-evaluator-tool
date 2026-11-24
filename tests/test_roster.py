import json
from pathlib import Path

from backend.config import Settings
from backend.repository import Repository
from backend.roster import match_roster


def test_roster_matches_email_not_similar_name_and_preserves_photo():
    users = [
        {
            "id": 12,
            "name": "New Name",
            "email": "AGENT@example.com",
            "status": "Active",
            "phone": "2155550100",
        }
    ]
    matches, missing = match_roster(
        [
            {
                "email": "agent@example.com",
                "name": "Old Name",
                "photo_url": "/agents/old.jpg",
            }
        ],
        users,
    )
    assert not missing
    assert matches[0]["name"] == "New Name" and matches[0]["fub_user_id"] == 12
    assert matches[0]["photo_url"] == "/agents/old.jpg"
    assert (
        match_roster([{"name": "New Name", "email": "different@example.com"}], users)[
            1
        ][0]["reason"]
        == "email_not_found"
    )


def test_roster_holds_duplicate_email_inactive_and_colliding_slug():
    user = {"id": 1, "name": "Same Name", "email": "a@example.com", "status": "Active"}
    assert (
        match_roster([{"email": "a@example.com"}], [user, user])[1][0]["reason"]
        == "ambiguous_email"
    )
    assert (
        match_roster([{"email": "a@example.com"}], [{**user, "status": "Invited"}])[1][
            0
        ]["reason"]
        == "inactive_user"
    )
    users = [user, {**user, "id": 2, "email": "b@example.com"}]
    assert (
        match_roster([{"email": u["email"]} for u in users], users)[1][0]["reason"]
        == "ambiguous_slug"
    )


def test_production_roster_is_email_verified_and_katie_is_explicitly_unresolved(
    tmp_path,
):
    path = Path(__file__).parents[1] / "config/agent-roster.json"
    data = json.loads(path.read_text())
    assert len(data["agents"]) == 56
    assert len({a["email"].lower() for a in data["agents"]}) == 56
    assert all(
        a["fub_user_id"] and not a["slug"].startswith("test-") for a in data["agents"]
    )
    assert data["generic_assignee"]["fub_user_id"] is None
    assert data["generic_assignee"]["name"] == "Katie Giardinelli"
    s = Settings(
        database_url="",
        database_path=str(tmp_path / "roster.db"),
        roster_path=str(path),
        vercel=False,
    )
    repo = Repository(s)
    repo.initialize()
    with repo.transaction() as db:
        db.execute(
            "UPDATE agents SET photo_url='/agents/mike-mccann.jpg' WHERE slug='mike-mccann'"
        )
        db.execute(
            "INSERT INTO agents(slug,name,email) VALUES('test-ben','Test','test@example.com')"
        )
    repo.initialize()
    assert repo.agent("mike-mccann")["photo_url"] == "/agents/mike-mccann.jpg"
    assert repo.agent("test-ben") is None
    assert len(repo.agents()) == 56
