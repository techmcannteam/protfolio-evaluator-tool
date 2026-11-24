"""File-backed roster and exact, case-insensitive FUB email matching."""

import json
import re
import unicodedata
from pathlib import Path


def slug_for(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60]


def match_roster(requested, users):
    matched, unmatched = [], []
    for source in requested:
        email = str(source.get("email") or "").strip().casefold()
        matches = [
            u
            for u in users
            if email and str(u.get("email") or "").strip().casefold() == email
        ]
        if len(matches) != 1:
            unmatched.append(
                {
                    "email": email,
                    "reason": "ambiguous_email" if matches else "email_not_found",
                }
            )
            continue
        user = matches[0]
        if user.get("status") != "Active" or user.get("deleted") or not user.get("id"):
            unmatched.append({"email": email, "reason": "inactive_user"})
            continue
        slug = source.get("slug") or slug_for(user["name"])
        if not re.fullmatch(r"[a-z0-9-]{1,60}", slug) or any(
            a["slug"] == slug for a in matched
        ):
            unmatched.append({"email": email, "reason": "ambiguous_slug"})
            continue
        matched.append(
            {
                "slug": slug,
                "name": user["name"].strip(),
                "email": email,
                "phone": str(user.get("phone") or "").strip(),
                "fub_user_id": user["id"],
                "photo_url": source.get("photo_url", ""),
            }
        )
    return matched, unmatched


def load_roster(path):
    data = json.loads(Path(path).read_text())
    seen = set()
    for agent in data["agents"]:
        slug = agent["slug"]
        if slug in seen or not re.fullmatch(r"[a-z0-9-]{1,60}", slug):
            raise ValueError("Roster contains duplicate or invalid slugs")
        seen.add(slug)
    if "mike-mccann" not in seen:
        raise ValueError("Roster must contain the public default Mike profile")
    return data
