"""Roster-controlled public identities. Never accept identities/URLs from visitors."""

import re

DEFAULT_SLUG = "mike-mccann"
SLUG = re.compile(r"[a-z0-9-]{1,60}\Z")


def public_agent(row):
    name = row.get("full_name") or row["name"]
    photo = row.get("photo_url") or f"/agents/{row['slug']}.jpg"
    if not (photo.startswith("/assets/") or re.fullmatch(r"/agents/[a-z0-9-]{1,60}\.jpg", photo)):
        photo = f"/agents/{row['slug']}.jpg"
    phone = row.get("phone") or ""
    if not re.fullmatch(r"\+?[0-9 ()\-.]{7,30}", phone):
        phone = ""
    email = row.get("email") or ""
    if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", email):
        email = ""
    return {
        "slug": row["slug"],
        "full_name": name,
        "first_name": row.get("first_name") or name.split()[0],
        "title": row.get("title") or "The Mike McCann Team · Keller Williams",
        "photo_url": photo,
        "phone": phone,
        "email": email,
    }


def resolve_agent(repository, slug):
    row = (
        repository.agent(slug)
        if isinstance(slug, str) and SLUG.fullmatch(slug)
        else None
    )
    return public_agent(row or repository.agent(DEFAULT_SLUG))
