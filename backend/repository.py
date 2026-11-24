"""SQLite locally, Neon Postgres on Vercel. Never accesses permit tables."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .roster import load_roster

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (slug TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, fub_user_id TEXT);
CREATE TABLE IF NOT EXISTS provider_cache (cache_key TEXT PRIMARY KEY, payload TEXT, expires_at DOUBLE PRECISION NOT NULL DEFAULT 0, lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, lease_token TEXT);
CREATE TABLE IF NOT EXISTS provider_calls (id TEXT PRIMARY KEY, provider TEXT NOT NULL, address TEXT NOT NULL, endpoint TEXT NOT NULL, cached INTEGER NOT NULL, status TEXT NOT NULL, timestamp DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS provider_calls_time ON provider_calls(timestamp);
CREATE TABLE IF NOT EXISTS counters (counter_key TEXT PRIMARY KEY, count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS estimates (id TEXT PRIMARY KEY, address TEXT NOT NULL, agent_slug TEXT, payload TEXT NOT NULL, timestamp DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS cma_requests (id TEXT PRIMARY KEY, estimate_id TEXT NOT NULL REFERENCES estimates(id), owner_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, property TEXT NOT NULL, our_estimate DOUBLE PRECISION NOT NULL, expected_value DOUBLE PRECISION, note TEXT NOT NULL, agent_slug TEXT NOT NULL REFERENCES agents(slug), timestamp DOUBLE PRECISION NOT NULL, fub_status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evaluation_leads (id TEXT PRIMARY KEY, payload TEXT NOT NULL, timestamp DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS evaluation_deliveries (evaluation_id TEXT NOT NULL REFERENCES evaluation_leads(id), kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(evaluation_id,kind));
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

    def initialize(self, *, seed_roster=True):
        with self.transaction() as db:
            if self.postgres:
                db.execute("SELECT pg_advisory_xact_lock(710272026)")
                db.execute("CREATE SCHEMA IF NOT EXISTS portfolio_evaluator")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            call_columns = (
                set()
                if self.postgres
                else {
                    r["name"]
                    for r in db.execute("PRAGMA table_info(provider_calls)").fetchall()
                }
            )
            if self.postgres or "http_status" not in call_columns:
                optional = "IF NOT EXISTS " if self.postgres else ""
                db.execute(
                    f"ALTER TABLE provider_calls ADD COLUMN {optional}http_status INTEGER"
                )
            # Additive migration preserves existing roster and future FUB mappings.
            columns = ["full_name", "first_name", "title", "photo_url", "phone"]
            existing = (
                set()
                if self.postgres
                else {
                    r["name"]
                    for r in db.execute("PRAGMA table_info(agents)").fetchall()
                }
            )
            for column in columns:
                if self.postgres or column not in existing:
                    optional = "IF NOT EXISTS " if self.postgres else ""
                    db.execute(
                        f"ALTER TABLE agents ADD COLUMN {optional}{column} TEXT NOT NULL DEFAULT ''"
                    )
            self._add_columns(db, "agents", {"active": "INTEGER NOT NULL DEFAULT 1"})
            self._add_columns(
                db,
                "evaluation_deliveries",
                {
                    "attempts": "INTEGER NOT NULL DEFAULT 0",
                    "updated_at": "DOUBLE PRECISION NOT NULL DEFAULT 0",
                    "next_attempt_at": "DOUBLE PRECISION NOT NULL DEFAULT 0",
                    "lease_token": "TEXT",
                    "last_error": "TEXT",
                },
            )
            if seed_roster:
                roster = load_roster(self.settings.roster_path)
                for agent in roster["agents"]:
                    name = agent["name"]
                    db.execute(
                        "INSERT INTO agents(slug,name,email,full_name,first_name,title,phone,fub_user_id,photo_url,active) VALUES(?,?,?,?,?,?,?,?,?,1) "
                        "ON CONFLICT(slug) DO UPDATE SET name=excluded.name,email=excluded.email,full_name=excluded.full_name,first_name=excluded.first_name,title=excluded.title,phone=excluded.phone,fub_user_id=COALESCE(excluded.fub_user_id,agents.fub_user_id),active=1,photo_url=CASE WHEN excluded.photo_url='' THEN agents.photo_url ELSE excluded.photo_url END",
                        (
                            agent["slug"],
                            name,
                            agent["email"],
                            name,
                            name.split()[0],
                            agent.get(
                                "title", "The Mike McCann Team · Keller Williams"
                            ),
                            agent.get("phone", ""),
                            str(agent["fub_user_id"])
                            if agent.get("fub_user_id")
                            else None,
                            agent.get("photo_url", ""),
                        ),
                    )
                for slug in roster.get("retired_slugs", []):
                    # Keep historical foreign keys; obsolete test links stop resolving.
                    db.execute("UPDATE agents SET active=0 WHERE slug=?", (slug,))

    def _add_columns(self, db, table, columns):
        existing = (
            set()
            if self.postgres
            else {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        )
        for name, definition in columns.items():
            if self.postgres or name not in existing:
                optional = "IF NOT EXISTS " if self.postgres else ""
                db.execute(
                    f"ALTER TABLE {table} ADD COLUMN {optional}{name} {definition}"
                )

    def agents(self):
        with self.transaction() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT slug,name FROM agents WHERE active=1 ORDER BY slug"
                ).fetchall()
            ]

    def agent(self, slug):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM agents WHERE slug=? AND active=1", (slug,)
            ).fetchone()
            return dict(row) if row else None

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
                self._log(db, provider, address, endpoint, False, "budget_exhausted")
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
            "INSERT INTO provider_calls(id,provider,address,endpoint,cached,status,timestamp) VALUES(?,?,?,?,?,?,?)",
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
                "UPDATE provider_calls SET status=?,http_status=? WHERE id=?",
                (payload["status"], payload.get("http_status"), token),
            )

    def cache_entries(self, keys):
        if not keys:
            return {}
        with self.transaction() as db:
            rows = db.execute(
                "SELECT * FROM provider_cache WHERE cache_key IN ("
                + ",".join("?" for _ in keys)
                + ")",
                tuple(keys),
            ).fetchall()
        return {
            r["cache_key"]: {
                **dict(r),
                "payload": json.loads(r["payload"]) if r["payload"] else None,
            }
            for r in rows
        }

    def provider_usage(self, provider):
        with self.transaction() as db:
            row = db.execute(
                "SELECT count FROM counters WHERE counter_key=?",
                (f"budget:{provider}:{int(time.time() // 86400)}",),
            ).fetchone()
        return row["count"] if row else 0

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

    def save_cma(self, request, estimate, status, *, lead=None, deliveries=None):
        # Repeated submissions of the same CMA are one request and one outbox event.
        identifier = str(
            uuid.uuid5(uuid.NAMESPACE_URL, "cma:" + request.model_dump_json())
        )
        with self.transaction() as db:
            inserted = db.execute(
                "INSERT INTO cma_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING RETURNING id",
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
            ).fetchone()
            if inserted and lead is not None:
                self._save_lead(db, identifier, lead, deliveries)
        return identifier

    def save_evaluation_lead(self, payload, deliveries):
        identifier = str(uuid.uuid4())
        with self.transaction() as db:
            self._save_lead(db, identifier, payload, deliveries)
        return identifier

    def _save_lead(self, db, identifier, payload, deliveries):
        now = time.time()
        db.execute(
            "INSERT INTO evaluation_leads VALUES(?,?,?)",
            (identifier, json.dumps(payload), now),
        )
        for kind, message in deliveries.items():
            message = {
                **message,
                "delivery_id": f"{identifier}:{kind}",
                "created_at": now,
            }
            waiting = kind == "owner_email"
            db.execute(
                "INSERT INTO evaluation_deliveries(evaluation_id,kind,payload,status,updated_at,next_attempt_at) VALUES(?,?,?,?,?,?)",
                (
                    identifier,
                    kind,
                    json.dumps(message),
                    "waiting_for_results" if waiting else "pending",
                    now,
                    now + self.settings.owner_email_delay_seconds if waiting else now,
                ),
            )

    def claim_delivery(self, identifier, kind, results_shown=False, *, retry=False):
        now = time.time()
        token = str(uuid.uuid4())
        condition = "status=?"
        args = ["waiting_for_results" if results_shown else "pending"]
        if retry:
            condition = "status IN ('pending','waiting_for_results','failed','disabled','needs_configuration') AND next_attempt_at<=? AND attempts<?"
            condition += " AND (status<>'waiting_for_results' OR (SELECT timestamp FROM evaluation_leads WHERE id=evaluation_id)<=?)"
            args = [
                now,
                self.settings.delivery_max_attempts,
                now - self.settings.owner_email_delay_seconds,
            ]
        with self.transaction() as db:
            row = db.execute(
                f"UPDATE evaluation_deliveries SET status='processing',lease_token=?,updated_at=? WHERE evaluation_id=? AND kind=? AND {condition} RETURNING payload,attempts",
                (token, now, identifier, kind, *args),
            ).fetchone()
            if row:
                created = db.execute(
                    "SELECT timestamp FROM evaluation_leads WHERE id=?", (identifier,)
                ).fetchone()["timestamp"]
        return (
            {
                "delivery_id": f"{identifier}:{kind}",
                "created_at": created,
                **json.loads(row["payload"]),
                "_claim_token": token,
                "_attempts": row["attempts"],
            }
            if row
            else None
        )

    def begin_delivery_attempt(self, identifier, kind, payload):
        clean = {k: v for k, v in payload.items() if not k.startswith("_")}
        with self.transaction() as db:
            row = db.execute(
                "UPDATE evaluation_deliveries SET attempts=attempts+1,payload=? WHERE evaluation_id=? AND kind=? AND status='processing' AND lease_token=? RETURNING attempts",
                (json.dumps(clean), identifier, kind, payload["_claim_token"]),
            ).fetchone()
        return row is not None

    def finish_delivery(self, identifier, kind, status, *, token, error=None):
        now = time.time()
        with self.transaction() as db:
            row = db.execute(
                "UPDATE evaluation_deliveries SET status=?,updated_at=?,next_attempt_at=?,last_error=?,lease_token=NULL WHERE evaluation_id=? AND kind=? AND status='processing' AND lease_token=? RETURNING kind",
                (
                    status,
                    now,
                    now + self.settings.delivery_retry_seconds,
                    error,
                    identifier,
                    kind,
                    token,
                ),
            ).fetchone()
            if row and kind == "fub":
                db.execute(
                    "UPDATE cma_requests SET fub_status=? WHERE id=?",
                    (status, identifier),
                )

    def recoverable_deliveries(self, limit=10):
        now = time.time()
        with self.transaction() as db:
            # A crashed sender might have transmitted. Hold it for reconciliation.
            db.execute(
                "UPDATE evaluation_deliveries SET status='uncertain',last_error='worker_interrupted',lease_token=NULL WHERE status='processing' AND updated_at<?",
                (now - 120,),
            )
            rows = db.execute(
                "SELECT evaluation_id,kind FROM evaluation_deliveries WHERE status IN ('pending','waiting_for_results','failed','disabled','needs_configuration') AND next_attempt_at<=? AND attempts<? AND (status<>'waiting_for_results' OR (SELECT timestamp FROM evaluation_leads WHERE id=evaluation_id)<=?) ORDER BY next_attempt_at,evaluation_id,kind LIMIT ?",
                (
                    now,
                    self.settings.delivery_max_attempts,
                    now - self.settings.owner_email_delay_seconds,
                    limit,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def delivery_statuses(self, identifier):
        with self.transaction() as db:
            return {
                r["kind"]: r["status"]
                for r in db.execute(
                    "SELECT kind,status FROM evaluation_deliveries WHERE evaluation_id=?",
                    (identifier,),
                ).fetchall()
            }
