# Agent roster, disabled senders, recovery and expenses

## Roster

`config/agent-roster.json` contains the owner-approved 54 active FUB Agent-role users plus Mike McCann and Ben Hooson Jones. The 56 accounts were matched by unique, case-insensitive email, not fuzzy names. The directory was fetched with one authenticated GET `/v1/users`, using the permit tool's existing credentials. No FUB writes occurred. See [the match report](agent-roster-match-2026-11-24.md).

Katie Giardinelli was absent from the returned directory; the owner believes she has no FUB account. Her generic-assignment config remains unresolved, with no guessed email or ID. Generic FUB deliveries are held as `needs_configuration`. A verified account/assignment is required before enabling generic delivery. Her email alone cannot serve as `person.assignedUserId`.

Roster initialization updates configured profiles and preserves existing photos when the roster has no replacement. Missing photos use the existing initials placeholder. Test agents are deactivated, not deleted, preserving historical CMA foreign keys. Test fixtures explicitly use a separate synthetic roster. No real agent data is needed by browser fixtures.

## Senders remain off

`ENABLE_FUB=false`, `ENABLE_EMAIL=false`, and `ENABLE_TEAM_NOTIFICATIONS=false` remain the defaults. No Vercel variables were changed. Flipping flags in the future enables real transports only when their required configuration is also present; this is no longer an always-simulated implementation.

FUB uses authenticated POST `/v1/events`, the same endpoint and Basic-auth/system-header pattern as the permit tool. Configure `FUB_API_KEY`, `FUB_SYSTEM` and the corresponding `FUB_SYSTEM_KEY` together. Explicit agent links retain their matched assignee; generic links use verified generic config. Home/portfolio source tags and assignment are included in evaluation and CMA events. CMA submissions use the saved estimate's routing and mode, never a client-supplied value; identical repeated CMA submissions share one outbox event. A new evaluation is a distinct event even if the address is unchanged.

Email uses Python's standard-library SMTP client with authenticated STARTTLS (587), or implicit TLS (465). Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and the verified website sender in `EMAIL_FROM`. `EMAIL_FROM` and `INTERNAL_NOTIFICATION_RECIPIENTS` are empty by default. No address, mailbox permission, password or provider subscription is assumed. HTML and plain-text alternatives share the site theme. Actual mailbox delivery is untested; all sender tests use mocked transports/stubs.

## Delivery recovery

The outbox persists payloads, status, attempts, claim tokens, timestamps, next eligibility and a redacted error code. A transaction claims one delivery; only that claim token may finalize it. Each email has a stable Message-ID. This is not a claim that SMTP or FUB provides an exactly-once transaction with Postgres.

A manual admin action is available at **POST `/api/admin/deliveries/retry`**. It requires `Authorization: Bearer <DELIVERY_ADMIN_TOKEN>` with a configured secret of at least 32 characters. Default token is empty, which denies access. The action processes at most one eligible delivery per request to fit a bounded Vercel request. No cron, scheduled build or deployment is created. Staff may repeat the action to drain eligible entries; all delivery flags still apply.

- `pending`: saved but not yet processed.
- `waiting_for_results`: owner email awaiting the normal browser callback. After `OWNER_EMAIL_DELAY_SECONDS` (default 900), admin recovery may process it without that callback.
- `disabled` / `needs_configuration`: no send; an explicit recovery action can revisit it after configuration and flag approval.
- `failed`: a confirmed rejection or pre-send connection failure. Retry waits `DELIVERY_RETRY_SECONDS` (default 300), with at most `DELIVERY_MAX_ATTEMPTS` (default 5) transport attempts.
- `processing`: one worker owns the claim. After 120 seconds without completion, recovery changes it to `uncertain`, not back to pending.
- `uncertain`: the service may already have accepted the request (lost response, interrupted worker, or partial SMTP recipient acceptance). Automatic/admin retry will not resend it. An operator must reconcile externally before any separate deliberate recovery; there is no blind force-resend endpoint.
- `sent`, `simulated`, `ignored`: terminal; repeated callbacks/retry actions do not send again. FUB HTTP 204 means an archived source ignored the event, not successful delivery.

Recovery uses stored recipients/content. Missing initial sender/team-recipient configuration can be filled from config before the first actual attempt. Missing FUB mapping is refreshed from the same agent's roster entry or the generic config; an unresolved explicit agent cannot fall back to another assignee. Legacy outbox payloads receive stable identifiers at claim time. The owner-email grace period also applies to legacy rows.

## Expense configuration

`config/expense-assumptions.json` is the single default block. `EXPENSE_ASSUMPTIONS_JSON` can override fields without code edits. Legacy `DEFAULT_*` environment variables remain compatible, but the JSON override takes precedence. No numbers were changed for Ben's December 1 decision.

Current defaults: 5% vacancy, 8% management, 5% of gross annual rent for maintenance, 0.5% of value for insurance, 1.4% of value for fallback tax. Actual/overridden taxes still take priority.

Maintenance supports `percent_rent` and `per_unit`. Insurance supports `percent_rent`, `per_unit`, and the existing `percent_value` mode. All dollar-per-unit amounts are **annual**, multiplied by the verified/owner-provided total unit count. A known single-home/condo type represents one unit; unknown multi-unit counts are never filled with one. Missing counts with per-unit expenses withhold NOI/cap and request review. Browser sliders use the configured unit basis and share tested arithmetic with the backend.

## Postgres verification

Vercel currently shares one database URL between Preview and Production; the owner explicitly authorized the scoped check on that shared database. `scripts/neon_delivery_smoke.py` requires an explicitly supplied `PREVIEW_DATABASE_URL`. It initializes only `portfolio_evaluator`, without roster seeding, and exercises synthetic lead/delivery persistence, concurrent claims, retries and missing-callback recovery. It deletes its rows in `finally` and verifies cleanup. It invokes no provider, SMTP or FUB sender. This check passed against Neon/Postgres, not just SQLite; no permit schema was accessed.

## References

- [FUB Events API](https://docs.followupboss.com/reference/events-post)
- [FUB users API and role mapping](https://docs.followupboss.com/reference/users-get)
- [Python SMTP client](https://docs.python.org/3/library/smtplib.html)
