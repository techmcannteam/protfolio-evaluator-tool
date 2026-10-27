# McCann Portfolio Evaluator backend

Python 3.13 / FastAPI / psycopg / Neon / Vercel, matching the permit backend conventions. Separate service/repository; Postgres queries use only the `portfolio_evaluator` schema. No permit code, deployment or public-schema tables are modified.

## Setup

```sh
uv sync --python 3.13
cp .env.example .env
# Set credentials privately in .env.
uv run uvicorn backend.main:app --reload --env-file .env
```

Open `/evaluator?agent=mike-mccann` for the owner experience and `/docs` for interactive API documentation and `/openapi.json` for the contract. Local development falls back to SQLite when DATABASE_URL is empty. Vercel requires DATABASE_URL and a random IP_HASH_SALT. Schema initialization is idempotent and serialized in Postgres.

## API

The original brief referred to “section 3” without supplying paths. These paths implement the requested behavior:

| Endpoint | Behavior |
|---|---|
| GET /health | Database health and simulated FUB status |
| GET /api/agents | Public agent slugs/names |
| GET /api/config | Assumptions, limits and disclaimer |
| POST /api/evaluate?agent=test-ben | Evaluate 1–10 addresses and portfolio totals |
| POST /api/cma-requests | Save a CMA request using a server-issued estimate id |

Evaluation example:

```json
{"addresses":[{"address":"2456 Sepviva St, Philadelphia, PA 19125","property_type":"Townhouse"}],"assumptions":{"vacancy":0.05}}
```

Addresses may also be strings. Property types are optional. Include city, state and ZIP; retain unit numbers. Duplicate normalized addresses are rejected. The agent may be supplied in the query or body; the query takes precedence.

CMA example (replace estimate_id with one returned by evaluation):

```json
{"estimate_id":"00000000-0000-0000-0000-000000000000","owner_name":"Example Owner","email":"owner@example.com","phone":"2155550100","agent_slug":"test-ben","expected_value":450000,"note":"Recently renovated kitchen."}
```

The property and our estimate are loaded from the saved server result, never trusted from the client. Attributed estimates cannot be reassigned to another agent. Contacts have no public read endpoint. The seeded `test-ben`, `test-nicole`, and `test-mccann` agents use example.com emails and are explicitly labeled test agents.

**FUB remains simulated.** ENABLE_FUB defaults to false; even when true, pushToFUB(request) is a no-network stub with a TODO for Events API lead creation and assignment. No CRM lead, email or notification is sent.

## Data and math

RentCast calls `/avm/value`, `/avm/rent/long-term`, and `/properties`. Optional ATTOM uses `/attomavm/detail` and `/valuation/rentalavm`, reusing the previous McCann comparison mappings. Disabled ATTOM makes no requests; RentCast works alone.

Property details are whitelisted: beds, baths, square footage, year built, last sale, matched address, property type and latest available annual property taxes. Ownership, demographics, schools and crime data are neither returned nor retained.

Value and rent estimates are medians across available sources. Low is the lowest reported low, high the highest reported high. Unblended estimates, bounds and available confidence are persisted in cache and estimate snapshots for later comparison. Bounds are descriptive, not calibrated confidence intervals. The backend uses the requested median rule, not the experimental Nicole outlier-trimming rule.

Confidence is heuristic: low above 20% disagreement or any provider score below 0.6; high for two or more sources agreeing within 10% with no available score below 0.8; medium otherwise. ATTOM confidence uses SCR/100 when SCR is within 0–100. FSD is retained as raw uncertainty and is not treated as a confidence probability. RentCast gets no invented provider score. Address or property-type mismatch warnings lower confidence. Labels are not probabilities.

NOI = annual rent × (1 − vacancy) − taxes − insurance − maintenance − management. Management and maintenance are fractions of gross rent; insurance and fallback taxes are fractions of value. Actual taxes override fallback taxes, unless the owner explicitly overrides annual_taxes. Zero actual taxes are retained. Defaults are **placeholders pending Ben's confirmation**. Debt service, financing, depreciation and income taxes are excluded.

Rates use decimals (0.046 = 4.6%), money is USD, rent is monthly and NOI is annual. Request-level overrides apply to all properties in that request. Omit annual_taxes to use each property's own taxes. Missing rent means null NOI/cap rate. Portfolio cap rate is total NOI / total value, not an average; partial portfolios have null cap rate and explicit completeness counts.

Every estimate includes: “Estimates are automated and not an appraisal. Ask your agent for a CMA.”

## Cost controls and security

- Successful endpoint responses cache for 30 days by normalized address, provider, endpoint and provider-affecting parameters. Unit numbers remain distinct. Assumption changes reuse provider data.
- Database leases prevent concurrent duplicate calls. Calls are reserved/logged before HTTP dispatch. Interrupted calls leave a pending audit entry and a 120-second lease.
- Negative matches cache for 24 hours; failures for five minutes. No HTTP retries or redirects. Concurrent callers briefly wait for an existing fetch, then return a busy partial result.
- Default shared daily cap: 30 actual HTTP calls **per provider**, excluding cache hits. This does not know the provider account's remaining monthly balance or calls from other tools.
- IP limits persist across Vercel instances: 20 evaluations/hour and 5 CMA requests/hour. IPs are HMAC-hashed; only Vercel's overwritten client-IP header is trusted in deployment.
- Provider audit records contain provider, normalized address, endpoint, cache flag, status and timestamp. No credentials, request headers, provider exception strings or contact payloads are logged.
- Keys remain server-side. Same-origin access by default; optional explicit CORS allowlist. Responses use no-store and noindex headers.
- Tables: portfolio_evaluator.agents, provider_cache, provider_calls, counters, estimates, cma_requests. The permit application's tables are outside the search path.

## Environment

| Variable | Default/purpose |
|---|---|
| DATABASE_URL | Neon connection string; required on Vercel |
| DATABASE_PATH | evaluator.sqlite3 locally |
| RENTCAST_API_KEY | Primary provider key |
| ATTOM_API_KEY / ENABLE_ATTOM | Optional provider; false by default |
| ENABLE_FUB | false; integration remains simulated even when true |
| IP_HASH_SALT | Private random value, required on Vercel |
| RATE_LIMIT_PER_HOUR | 20 |
| PROVIDER_DAILY_CALL_LIMIT | 30 per provider per UTC day; 0 blocks misses |
| ALLOWED_ORIGINS | Optional explicit comma-separated frontend origins |
| DEFAULT_VACANCY | 0.05 |
| DEFAULT_MANAGEMENT | 0.08 |
| DEFAULT_MAINTENANCE | 0.05 |
| DEFAULT_INSURANCE_RATE | 0.005 |
| DEFAULT_FALLBACK_TAX_RATE | 0.014 |

## Tests and comparison

```sh
uv run pytest -q
uv run ruff check backend tests scripts
uv run python -m scripts.compare
uv run python -m scripts.neon_smoke
```

Neon smoke loads .env, checks evaluator cache/budget/estimates/CMA persistence with synthetic contacts, then deletes those contact rows. It does not access permit tables.

Default comparison uses sanitized historical responses from October 21–23, 2026: ten real Philly/Main Line properties, including rowhomes, a condo and multifamily. **Zero network calls.** See [comparison](docs/comparison.md). Missing values/rents remain N/A, including multifamily rent. Historical estimates are not current values; comparison to historical sales does not establish predictive accuracy.

For a deliberate fresh run, load credentials into the process environment and run `python -m scripts.compare --live`. It prints the upper-bound call plan (up to 30 RentCast and 20 ATTOM before cache), respects the daily cap and does not retry failures. ATTOM requires both key and enable flag. Prefer a one-property smoke test when quota is limited.

## Preview deployment

Vercel project `mccann-portfolio-evaluator`, team `the-mike-mc-cann-team`. `pyproject.toml` sets backend.main:app following [Vercel FastAPI documentation](https://vercel.com/docs/frameworks/backend/fastapi). Configure Preview environment variables securely, then deploy with:

```sh
vercel deploy --target preview --scope the-mike-mc-cann-team
```

Vercel rejected automatic GitHub linking (`repo_no_access`); CLI snapshot deployment is independent. Automatic deployments on push are not configured. No production promotion is implied. This preview seeds test agents and simulates CMA delivery; replace test agents and implement the approved delivery/access/retention workflow before a consumer rollout.


## Frontend and sending-agent identity

The responsive owner flow uses the supplied skyline, interior and McCann logo assets, Cormorant Garamond/Lato typography, square red buttons, underline inputs and white/black panels. It includes landing, loading, results, assumption controls, per-property CMA form, honest simulated-delivery confirmation, and not-found/limit/service errors. Address suggestions use Google Places API (New) through server-only endpoints, with a Philadelphia location bias, US address filtering, keyboard selection, and ZIP completion. Manual entry remains available. Backend financial defaults/formulas remain authoritative rather than adopting the mockups' conflicting sample defaults. Confidence descriptions reflect the actual backend heuristic, not unsupported claims about nearby comp counts.

`GET /api/agent?slug=...` resolves a roster-controlled identity with `slug`, `full_name`, `first_name`, `title`, `photo_url`, `phone`, `email`. Invalid, absent and unknown slugs fall back to `mike-mccann`. Slugs accept only lowercase letters, digits and hyphens, up to 60 characters. Names and photo URLs are never taken from query parameters. Public responses omit FUB user IDs. Profile photos allow HTTPS or local /assets/ paths; unsafe schemes are discarded.

An additive migration extends the existing agents table without overwriting configured profiles or FUB IDs. The default Mike McCann identity has empty photo/contact fields until verified roster data is connected. Missing/broken photos show initials on #d9d9d9; contact links are disabled when no verified contact is available. Agent photos are exactly 72×88 on landing, 38×46 on results, and 60×72 on the error strip, with cover cropping and center-top alignment.

All screen navigation retains the server-resolved `?agent=` slug. Evaluation snapshots and CMA requests store that slug, and mismatched CMA attribution is rejected server-side. Follow Up Boss delivery is still simulated; the preview clearly says requests are saved and no notification is sent. The future FUB connection must populate the roster and map each slug to its FUB user ID before real assignment is enabled.

### Browser tests

```sh
npm ci --ignore-scripts
npx playwright install chromium
npm run test:browser
```

Browser tests start a local FastAPI instance with a temporary SQLite database, synthetic agents and a synthetic valuation provider. They never read .env or call RentCast, ATTOM or Follow Up Boss. They cover fallback slugs, query injection, valid/missing/broken images, exact avatar dimensions, loading/results identity, sliders, personalized modal/consent/confirmation, correct submitted agent_slug, tel/mailto links, error states, mobile/desktop overflow and browser errors. `CHROMIUM_PATH` optionally selects an existing Chromium; `SCREENSHOT_DIR` optionally saves review images. Both browser and Python tests run in CI.

### CSV property import

The landing page accepts UTF-8 `.csv` files up to 100 KB. Use an `address` column with quoted full addresses, or `street,city,state,zip` columns with an optional `unit` column. A downloadable template is available on the page. Import appends unique addresses to existing entries, enforces the combined 10-property limit, and leaves entries unchanged on validation failure. Addresses remain editable; no valuation requests run until the user submits the evaluation form. Files are parsed locally in the browser.

Run CSV parser tests with `npm run test:csv`; the browser suite also covers import and subsequent evaluation with agent attribution.

Autocomplete requires `GOOGLE_PLACES_API_KEY` on the server. Requests are debounced 350 ms after four characters; session tokens join predictions and selected-place details. Suggestions are not cached. Limits: 120 requests per IP per hour and 1,000 Places requests per day across the project. Google Maps attribution appears below suggestions.
