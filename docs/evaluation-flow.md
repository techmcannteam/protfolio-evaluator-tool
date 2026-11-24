# Home and portfolio evaluations — Ben’s November 2 requirements

Implemented locally November 24, 2026. RentCast only, ATTOM off. No provider calls, live emails, FUB submissions, team messages or deployments were used to implement or test this change.

## Display and condition

Each property shows its most likely indication in large type, with the provider range beneath it. Range endpoints are presented as a condition guide: **needs work** to **renovated / updated**. These labels are product guidance, not a new provider appraisal or a statistical confidence interval.

Each address has “Kitchen or baths updated in the last 5 years?” with Yes, No and Not sure. `recently_updated=true` points to `max(provider estimate, low + 0.8 × (high − low))`, rounded to cents, within a complete valid range. It never lowers an already higher estimate. No/unknown leave the indication at the provider estimate. Missing, zero-width or invalid ranges cannot support a condition adjustment.

`display_value` is separate from `value`, `rent`, provider sources, bounds and cached responses. Provider request parameters and cache keys are unchanged by the condition answer. NOI and cap rates continue to use provider values and existing operating assumptions. Portfolio display totals sum the available display indications; API financial totals retain provider values. The exact disclaimer remains: “Estimates are automated and not an appraisal. Ask your agent for a CMA.”

## Two links and contact step

- `/evaluator/home`: one address, no CSV/add-address controls, compact result view and optional property details. The public API rejects multiple addresses in `mode=home`.
- `/evaluator/portfolio`: up to ten addresses, CSV upload and existing rental/assumption controls.
- `/evaluator` remains a compatible entry into portfolio mode.
- Both links preserve recognized `?agent=<slug>` personalization through contact, results and CMA navigation. Missing or invalid links display Mike’s public profile but remain generic; they are not rewritten as explicit Mike links.

Address entry is step one. Name and email are required in step two; phone is optional. `/api/evaluate` also requires these contact fields, so the UI gate cannot be bypassed by omitting contact data. `PublicEvaluateRequest` handles public validation; the internal evaluator remains usable by offline analysis scripts. Any HTTP batch caller must now supply a contact and mode.

Contact details and the authoritative result snapshot are stored in `evaluation_leads`. Prepared follow-up payloads and statuses are stored in `evaluation_deliveries`. These are additive tables in the evaluator’s existing SQLite / `portfolio_evaluator` Postgres schema. No migration is run against a remote database during this work. There is no public lead/contact read endpoint, and responses omit recipient lists, contact data and FUB user IDs.

## Follow-ups and configuration

Updated delivery implementation: see [delivery rollout](delivery-rollout.md) for real-but-disabled FUB/SMTP senders, the verified roster, and admin recovery.

| Setting | Default | Purpose |
| --- | --- | --- |
| `ENABLE_EMAIL` | `false` | Gate owner-summary sender and all email delivery |
| `EMAIL_FROM` | empty | Easily replaceable sender address |
| `ENABLE_TEAM_NOTIFICATIONS` | `false` | Additional gate for internal email |
| `INTERNAL_NOTIFICATION_RECIPIENTS` | empty | Comma-separated internal recipient list |
| `ENABLE_FUB` | `false` | Gate real FUB Events delivery (off by default) |
| `FUB_GENERIC_ASSIGNEE_ID` | empty | Mike McCann’s assistant’s verified FUB user ID |
| `ENABLE_ATTOM` | `false` | Retained adapter, inactive |

Default implementations are now real FUB Events and SMTP senders, gated off. Configuration and explicit approval are required before enabling them. Tests inject recording senders or mock HTTP/SMTP. No credentials, sender address, recipients or assistant user ID are invented or committed.

Every valid completed evaluation prepares a team notification and FUB event, including evaluations returning unavailable values. The internal summary contains owner name/email/optional phone, the home/portfolio agent link, all addresses, individual results, totals and routing status. Empty recipients or missing sender/assignee configuration prevent dispatch. Invalid submissions and rate-limited requests are not evaluations and do not create leads.

The owner summary is prepared but waits until the browser renders results and posts `/api/evaluations/{evaluation_id}/results-shown`. The callback uses the opaque server-issued UUID and cannot supply or replace email recipients, financial data or message content. Atomic status claims prevent duplicate delivery on repeated callbacks. Confirmed failures are recorded as `failed`; uncertain acceptance is held for reconciliation. The authenticated admin retry action handles eligible failures and owner emails missing their callback after a 15-minute grace period. No cron is enabled.

## Follow Up Boss routing

Known explicit agent links use the roster’s `agents.fub_user_id`. Generic, unknown or invalid links use `FUB_GENERIC_ASSIGNEE_ID`. An explicit Mike link routes to Mike’s roster ID; a generic link routes to the configured assistant. Missing agent mappings are flagged `needs_configuration`, never reassigned to another agent or guessed.

Prepared [FUB Events API](https://docs.followupboss.com/reference/events-post) payloads use `type=Seller Inquiry`, `source=McCann Home Evaluation` or `McCann Portfolio Evaluation`, contact arrays under `person`, `person.assignedUserId`, and `person.tags` containing `home-evaluation` or `portfolio-evaluation`. The server-calculated summary is included in the description. This follows the permit tool’s Events API shape without borrowing its live sender or credentials. CMA delivery uses the same disabled real sender and durable outbox.

## Verification

Python tests use synthetic providers, temporary SQLite and outbound-network blocking. Coverage includes condition calculation and provider/cap invariance, contact validation, both URL modes, agent versus generic routing, explicit Mike routing, missing mappings, payload tags, disabled flags, sender replacement, result-display timing, notification failures and concurrent/repeated delivery claims.

Browser tests retain the existing regression scenarios and add both links at 1440px and 390px, address-first contact gating, optional phone, condition indication with unchanged bounds, generic attribution and return navigation. External browser requests are blocked. Set `SCREENSHOT_DIR` outside the repository to retain entry/contact/results screenshots. Local browser tests require localhost binding and Chromium; no Vercel build is needed.
