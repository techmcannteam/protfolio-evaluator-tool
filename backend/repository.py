"""SQLite locally, Neon Postgres on Vercel. Never accesses permit tables."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (slug TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, fub_user_id TEXT);
CREATE TABLE IF NOT EXISTS provider_cache (cache_key TEXT PRIMARY KEY, payload TEXT, expires_at DOUBLE PRECISION NOT NULL DEFAULT 0, lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, lease_token TEXT);
CREATE TABLE IF NOT EXISTS provider_calls (id TEXT PRIMARY KEY, provider TEXT NOT NULL, address TEXT NOT NULL, endpoint TEXT NOT NULL, cached INTEGER NOT NULL, status TEXT NOT NULL, timestamp DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS provider_calls_time ON provider_calls(timestamp);
CREATE TABLE IF NOT EXISTS counters (counter_key TEXT PRIMARY KEY, count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS estimates (id TEXT PRIMARY KEY, address TEXT NOT NULL, agent_slug TEXT, payload TEXT NOT NULL, timestamp DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS cma_requests (id TEXT PRIMARY KEY, estimate_id TEXT NOT NULL REFERENCES estimates(id), owner_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, property TEXT NOT NULL, our_estimate DOUBLE PRECISION NOT NULL, expected_value DOUBLE PRECISION, note TEXT NOT NULL, agent_slug TEXT NOT NULL REFERENCES agents(slug), timestamp DOUBLE PRECISION NOT NULL, fub_status TEXT NOT NULL);
"""


class Session:
    def __init__(self, connection, postgres):
        self.connection, self.postgres = connection, postgres

    def execute(self, query, args=()):
        return self.connection.execute(
            query.replace("?", "%s") if self.postgres else query, args
        )


class Repository:
    def __init__(self, settings):
        self.settings = settings
        self.postgres = bool(settings.database_url)
        if settings.vercel and not self.postgres:
            raise RuntimeError("DATABASE_URL is required on Vercel.")

    @contextmanager
    def transaction(self):
        if self.postgres:
            conn = psycopg.connect(
                self.settings.database_url, connect_timeout=10, row_factory=dict_row
            )
            conn.execute("SET search_path TO portfolio_evaluator")
        else:
            conn = sqlite3.connect(self.settings.database_path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield Session(conn, self.postgres)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.transaction() as db:
            if self.postgres:
                db.execute("SELECT pg_advisory_xact_lock(710272026)")
                db.execute("CREATE SCHEMA IF NOT EXISTS portfolio_evaluator")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            for slug, name in [
                ("test-ben", "Ben — Test Agent"),
                ("test-nicole", "Nicole — Test Agent"),
                ("test-mccann", "McCann — Test Agent"),
            ]:
                db.execute(
                    "INSERT INTO agents(slug,name,email) VALUES(?,?,?) ON CONFLICT(slug) DO NOTHING",
                    (slug, name, slug + "@example.com"),
                )

    def agents(self):
        with self.transaction() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT slug,name FROM agents ORDER BY slug"
                ).fetchall()
            ]

    def agent_exists(self, slug):
        return any(x["slug"] == slug for x in self.agents())

    def consume(self, key, limit):
        with self.transaction() as db:
            return self._consume(db, key, limit)

    @staticmethod
    def _consume(db, key, limit):
        row = (
            db.execute(
                "INSERT INTO counters(counter_key,count) VALUES(?,1) ON CONFLICT(counter_key) DO UPDATE SET count=counters.count+1 WHERE counters.count < ? RETURNING count",
                (key, limit),
            ).fetchone()
            if limit > 0
            else None
        )
        return row is not None

    def claim(self, key, provider, address, endpoint, budget):
        now = time.time()
        with self.transaction() as db:
            db.execute(
                "INSERT INTO provider_cache(cache_key) VALUES(?) ON CONFLICT(cache_key) DO NOTHING",
                (key,),
            )
            suffix = " FOR UPDATE" if self.postgres else ""
            row = db.execute(
                "SELECT * FROM provider_cache WHERE cache_key=?" + suffix, (key,)
            ).fetchone()
            if row["payload"] is not None and row["expires_at"] > now:
                self._log(db, provider, address, endpoint, True, "cache_hit")
                return "cached", json.loads(row["payload"]), None
            if row["lease_until"] > now:
                return "busy", None, None
            if not self._consume(db, f"budget:{provider}:{int(now // 86400)}", budget):
                return "budget_exhausted", None, None
            token = str(uuid.uuid4())
            db.execute(
                "UPDATE provider_cache SET lease_until=?,lease_token=? WHERE cache_key=?",
                (now + 120, token, key),
            )
            self._log(db, provider, address, endpoint, False, "pending", token)
            return "fetch", None, token

    @staticmethod
    def _log(db, provider, address, endpoint, cached, status, token=None):
        db.execute(
            "INSERT INTO provider_calls VALUES(?,?,?,?,?,?,?)",
            (
                token or str(uuid.uuid4()),
                provider,
                address,
                endpoint,
                int(cached),
                status,
                time.time(),
            ),
        )

    def finish(self, key, token, payload, ttl):
        with self.transaction() as db:
            db.execute(
                "UPDATE provider_cache SET payload=?,expires_at=?,lease_until=0,lease_token=NULL WHERE cache_key=? AND lease_token=?",
                (json.dumps(payload), time.time() + ttl, key, token),
            )
            db.execute(
                "UPDATE provider_calls SET status=? WHERE id=?",
                (payload["status"], token),
            )

    def save_estimate(self, address, agent, payload):
        identifier = str(uuid.uuid4())
        with self.transaction() as db:
            db.execute(
                "INSERT INTO estimates VALUES(?,?,?,?,?)",
                (identifier, address, agent, json.dumps(payload), time.time()),
            )
        return identifier

    def estimate(self, identifier):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM estimates WHERE id=?", (identifier,)
            ).fetchone()
            return dict(row) if row else None

    def save_cma(self, request, estimate, status):
        identifier = str(uuid.uuid4())
        with self.transaction() as db:
            db.execute(
                "INSERT INTO cma_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    request.estimate_id,
                    request.owner_name,
                    str(request.email),
                    request.phone,
                    estimate["address"],
                    json.loads(estimate["payload"])["value"]["estimate"],
                    request.expected_value,
                    request.note,
                    request.agent_slug,
                    time.time(),
                    status,
                ),
            )
        return identifier
