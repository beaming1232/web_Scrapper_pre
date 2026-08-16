# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

India Job Aggregator — scraping + AI-rewrite pipeline, a read-only HTTP API on top, and a
Next.js frontend on top of that. Backend is Python 3.11+, async throughout (httpx +
SQLAlchemy 2.0 async + asyncpg); frontend is TypeScript (Next.js 16 App Router + React 19
+ Tailwind v4) in `frontend/`, a separate npm project with its own dependencies.

**Phase 2 has started**: scraped descriptions are rewritten by an LLM before storage
(`pipeline/rewriter.py`) — see that module's docstring for the why (copyright risk +
AdSense "scraped content" policy) and the "AI description rewriting" section below for
the non-obvious details. Provider is Google Gemini's REST API called over the existing
httpx dependency — still no `anthropic` SDK (nor `google-generativeai`), and don't add
either without checking with the user first; that specific choice hasn't changed even
though the phase boundary and the provider (DeepSeek → Gemini, per direct user
instruction) both have.

**Phase 3 is underway**: a read-only FastAPI layer (`api/`) sits in front of the `jobs`
table, and a Next.js frontend (`frontend/`) consumes it — see the "Read API" and
"Frontend" sections below for the non-obvious details (the `description` fallback logic
in particular, which spans both). `api/` shares `db/session.py`'s async engine/session
factory but never scrapes, rewrites, or writes; everything upstream of it (scraping,
filtering, dedup, rewriting, storage) is unchanged.

**Database is Neon (hosted Postgres), not local** — this changed on 2026-08-13. A local
PostgreSQL 18 service was used earlier in development and is no longer read by anything;
`DATABASE_URL` in `.env` now points at a Neon project (`...neon.tech`), migrated via
`alembic upgrade head`, and `jobs/scrape_all.py`/`api/` both verified working end-to-end
against it live (confirmed by comparing row counts: local stayed frozen while Neon's grew
from a scrape run). Two non-obvious things about the Neon connection string specifically:
  - **`sslmode=require` (Neon's own copy-paste default) does not work with asyncpg** —
    confirmed by testing, not assumed: it raises `TypeError: connect() got an unexpected
    keyword argument 'sslmode'`, because `sslmode` is a psycopg/libpq-ism asyncpg's own
    `connect()` doesn't accept. Use `ssl=require` instead, which asyncpg does understand.
    `channel_binding=require` (also in Neon's default string) is dropped entirely — not a
    recognized asyncpg param, and asyncpg's SSL negotiation covers it anyway.
  - The hostname has `-pooler` in it (Neon's PgBouncer-pooled endpoint). Verified this
    doesn't trip the classic pgbouncer+asyncpg "prepared statement already exists" issue
    for this app's usage: 8 repeated queries across separate sessions all succeeded, and
    `alembic upgrade head`'s DDL ran clean against it too. If a `psycopg`-style prepared-
    statement error ever does show up, Neon also exposes a non-pooled/direct connection
    string as an alternative - swap to that for migrations specifically if so.

If you're picking this repo up somewhere Postgres genuinely isn't set up yet at all
(neither Neon nor local), everything before the DB-write step (fetch/parse/normalize/
filter/resolve) can still be run and verified without a database; see "Previewing
scraper output without Postgres" below.

**This is deployed and live as of 2026-08-14** — see "Deployment" below. The repo root is
now a real git repo (`beaming1232/web_Scrapper_pre` on GitHub, branch `main`), the stray
`frontend/.git` nested repo noted at the bottom of the Frontend section has been dealt
with, and Railway auto-deploys `main` on every push.

AI rewriting is currently **disabled** (`REWRITE_ENABLED=false` in `.env`) — no paid
Gemini plan yet, and the free-tier key was already hitting `429` quota errors mid-run
(see git history / the 2026-08-13 scrape: 17 jobs stored, only 10 got a real rewrite
before quota ran out). Scraping and storage work fully regardless — jobs just get
stored with `rewritten_description=None`, same as any other rewrite failure, and
`api/`'s `description` field falls back to `description_original` for those rows in the
meantime. Flip `REWRITE_ENABLED=true` once a paid/higher-quota key is available, then
backfill the NULL rows rather than re-scraping (see `pipeline/rewriter.py`'s docstring).
`REWRITE_ENABLED` must be set **per Railway service** too, not just in `.env` — the
scraper service was found on 2026-08-14 with it `true` and no `GEMINI_API_KEY` set at
all, and was corrected to `false`; see "Deployment" below.

## Deployment (live since 2026-08-14)

Three moving parts, all deploying from the same GitHub repo
(`beaming1232/web_Scrapper_pre`, branch `main`):

- **Backend API** — Railway service `web_Scrapper_pre`, always-on web process,
  `uvicorn api.main:app --host 0.0.0.0 --port $PORT` (from `railway.json`), public at
  `https://webscrapperpre-production.up.railway.app`. Healthcheck `/health`.
- **Scraper cron** — Railway service `diplomatic-amazement`, **same repo, separate
  service**, start command `python -m jobs.scrape_all`, Railway-native Cron Schedule
  `0 */6 * * *`. It is not a web service: it runs to completion and exits, which is
  exactly the shape `jobs/scrape_all.py` already had (`asyncio.run(main())`).
- **Frontend** — Vercel, consuming the Railway API over `API_BASE_URL`.

Non-obvious things about this setup, all learned the hard way:

- **APScheduler is still not used, deliberately.** `requirements.txt` ships it and
  `jobs/scrape_all.py`'s docstring shows how to wire it, but nothing does — scheduling is
  Railway's cron feature instead. Don't "finish" that wiring by starting a scheduler
  inside `api/main.py`'s lifespan: the Read API section's rule that `api/` only ever reads
  and the pipeline only ever writes is an architecture boundary, and folding them into one
  process also means a hung scrape can take the live API down with it.
- **Railway dashboard settings override `railway.json`.** Both services read the same
  `/railway.json`, so the scraper's `startCommand` and `cronSchedule` live in its
  dashboard/service settings, *not* in that file — putting `cronSchedule` in
  `railway.json` would apply it to the API service too. (`startCommand` was removed from
  `railway.json` for this reason in commit `8e1734f`.)
- **`railway redeploy` does NOT trigger a cron run.** It only refreshes the build; the
  instance goes to `CREATED` and never `RUNNING`, and no logs appear. There is no
  "run cron now" in the CLI (the dashboard has a Run Now button). The genuine CLI
  equivalent is `railway run -s <service> -- <cmd>`, which pulls that service's real
  production env vars and runs the command locally against the same Neon DB:

  ```bash
  railway run -s diplomatic-amazement -- ./.venv/Scripts/python.exe -m jobs.scrape_all
  ```
- **Env vars are per-service on Railway and drift from `.env`.** The scraper service was
  found with `REWRITE_ENABLED=true` but **no `GEMINI_API_KEY` at all** — every rewrite
  would have failed harmlessly but burned retries per insert. Set to `false` on
  2026-08-14 to match `.env`/this file. Check both services' vars, not just `.env`, when
  something behaves differently in production.
- **Two GitHub accounts are stored in `~/.git-credentials`** (`beaming1232` and
  `sachinyeole1232`) and git picks the wrong one, failing with `403 ... denied to
  sachinyeole1232`. Push with the account in the URL:
  `git push https://beaming1232@github.com/beaming1232/web_Scrapper_pre.git main`.

### Why the API "crashed sometimes" (2026-08-16) — healthcheck coupled to Neon

**`/health` was Railway's `healthcheckPath` *and* a hard database dependency, so
a cold Neon compute killed otherwise-healthy deployments.** Symptom was
intermittent "deployment crashed" emails with no reproducible trigger.

`api/routers/health.py` used to declare `session: AsyncSession = Depends(get_db)`
and run `SELECT 1` unguarded. Because the failure happened *inside the FastAPI
dependency*, before the handler body, it could not be turned into a graceful
response — it surfaced as a bare 500:

```
ConnectionRefusedError: [Errno 111] Connection refused
INFO:  100.64.0.2:49239 - "GET /health HTTP/1.1" 500 Internal Server Error
```

Railway read that 500 as "unhealthy", failed the deploy inside
`healthcheckTimeout`, burned `restartPolicyMaxRetries`, and emailed a crash
notice — for a process that was alive and a database that returned seconds
later. Deploys landing while Neon's compute was scaled to zero died; deploys
that didn't, survived. That coin-flip is the whole "sometimes".

Neon (free tier) scales compute to zero when idle, and the cold connect is
genuinely slow — **measured 8.0s** on a real cold start (and >5s repeatedly),
against ~1.9s warm. Anything that treats a slow database as a dead one will
therefore misfire.

The fix, and the rules that follow from it:

- **Liveness and readiness are separate endpoints, and only liveness gates the
  container.** `GET /health` always returns 200 while the process is up, and
  reports the database in its `database` field as *data* (`connected` /
  `unreachable`) rather than as an HTTP failure. `GET /health/db` is the
  readiness check and *does* return 503 — point monitoring there. Do not
  re-couple `/health` to the database, and do not point Railway's
  `healthcheckPath` at `/health/db`; that recreates the outage exactly.
- The probe is bounded by `health_db_probe_timeout_seconds` (15s) so a *hung*
  connection, not just a refused one, cannot stall the healthcheck. That value
  deliberately sits above a real Neon cold start and below
  `healthcheckTimeout` (now 120s). Setting it below ~10s makes a merely-cold
  database report `unreachable` — verified: at 5s the probe timed out and
  reported `unreachable` while `/jobs` served a 200 from the same database.
- `db/session.py` sets `pool_recycle` + `pool_timeout` and passes asyncpg
  `timeout`/`command_timeout` via `connect_args`. `pool_pre_ping` alone only
  catches a connection that already died; `pool_recycle` stops it going stale
  against Neon's `-pooler` endpoint, which closes idle server-side connections.
  `_asyncpg_connect_args()` is guarded on `+asyncpg` being in the URL because
  those kwargs are asyncpg's own and raise on any other DBAPI.
- `tests/test_health.py::test_health_returns_200_when_database_is_unreachable`
  is the regression guard. If it goes red, the intermittent deploy crashes are
  back.

**Also worth knowing**: the Railway service runs in `ams` (Amsterdam) while Neon
is in `us-east-2` (Ohio), so every database round trip crosses the Atlantic —
that is why a warm `SELECT 1` costs ~1.6s from the container. Not a bug, but it
shrinks the margin on anything time-bounded that touches the DB.

## Commands

```bash
# Environment (Windows; this repo has no venv checked in)
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# Tests (no pytest.ini — plain pytest discovery)
# NOTE: 5 tests in tests/test_rewriter.py fail on a clean checkout — pre-existing, not
# your change. REWRITE_ENABLED=false from .env leaks into the test process, so those
# tests build a disabled rewriter and no HTTP call is made. 88 pass. Fix by having the
# rewriter tests force enabled=True rather than inheriting settings, if it ever matters.
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m pytest tests/test_jobfound.py -v
./.venv/Scripts/python.exe -m pytest tests/test_talentd.py -v
./.venv/Scripts/python.exe -m pytest tests/test_jobfound.py::test_listing_with_salary_present -v

# DB migrations (requires DATABASE_URL in .env, Postgres reachable)
alembic upgrade head

# Run the real pipeline (requires Postgres set up)
python -m jobs.scrape_all      # runs every registered source once
python -m jobs.health_check    # HEAD-checks active apply_urls, deactivates dead links

# Run the read-only API (requires Postgres set up; see "Read API" below)
./.venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000
# then: http://127.0.0.1:8000/docs for interactive OpenAPI docs
```

```bash
# Frontend (separate npm project in frontend/; needs the API above running)
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run build    # production build; also type-checks
npx tsc --noEmit # type-check only
```

Both servers must be running to see data locally: the frontend server-renders by calling
the API, so with the API down every page renders its "Could not load jobs" state rather
than failing outright.

There is no lint/format/type-check tooling configured in this repo (no ruff/black/mypy
config) — don't assume one exists.

## Architecture

Pipeline, in order, wired together only in `pipeline/runner.py`:
```
scrapers/sources/{name}.py (BaseSource subclass: fetch → parse → normalize)
  → scrapers/registry.py auto-discovers it (zero manual wiring)
  → pipeline/runner.py orchestrates:
      finalize (id/fingerprint/scraped_at, pipeline/dedup.py)
      → filter_external pass 1 (pipeline/filter.py::apply_external_filter, pre-resolution)
      → resolve_url (pipeline/resolver.py, HEAD requests, up to 3 redirect hops)
      → filter_external pass 2 (pipeline/filter.py::revalidate_after_resolution, post-resolution)
      → dedup (pipeline/dedup.py::find_duplicate / merge_into_existing)
      → rewrite (pipeline/rewriter.py::DescriptionRewriter, new inserts only — see below)
      → store (db/models.py::JobModel via db/session.py)
```

**Adding a new source = one new file** in `scrapers/sources/`, subclassing `BaseSource`
(`scrapers/base.py`) and implementing `fetch()`/`parse()`/`normalize()`. Nothing else
changes — `scrapers/registry.py` discovers it by scanning that directory. `normalize()`
must never raise on a missing field (canonical schema has documented defaults for
everything except `title`/`company`/`source`/`raw_apply_url`) and must populate
`source_fields_missing` with the canonical field names it couldn't extract.

**Canonical schema** lives in `db/models.py` in two forms that must stay in sync:
`JobSchema` (Pydantic, what `normalize()` output is validated against) and `JobModel`
(SQLAlchemy ORM, the `jobs` table). A scraper's `normalize()` sets `apply_type`
(EXTERNAL/DIRECT/UNKNOWN); it never sets `is_external` — that's derived entirely by the
pipeline's two filter passes below.

**Why the external-link filter runs twice**, not once (`pipeline/filter.py`): a
scraper's `apply_type` classification only ever sees the *raw*, pre-resolution URL. A
tracker link can look external but redirect to a known aggregator domain (LinkedIn,
Naukri, etc. — `KNOWN_AGGREGATOR_DOMAINS` in `pipeline/filter.py`, the single source of
truth other modules import rather than duplicate) that only becomes visible after
`pipeline/resolver.py` follows the redirect chain. Pass 1 runs pre-resolution on
`apply_type`; pass 2 (`revalidate_after_resolution`) re-checks the *resolved* domain
post-resolution and downgrades/drops anything that lands on an aggregator after all.
Architecture rule: `is_external=False` always means discard entirely, at either pass —
never persisted with the flag set to False.

**Dedup** (`pipeline/dedup.py`) keys primarily on `fingerprint` (hash of
slugified title+company+location), secondarily on `resolved_domain` + apply URL path. A
duplicate updates `scraped_at` and appends to `merged_sources` on the existing row
rather than inserting a new one.
  - `find_duplicate()` **must `flush()` before querying** — `db/session.py` sets
    `autoflush=False`, so rows added earlier in the same batch are still pending and
    invisible to a plain `SELECT`. Without it, two jobs sharing a fingerprint in one run
    each miss the other and both get inserted. Don't remove that flush.
  - The fingerprint lookup uses `.first()` on an ordered query, **not**
    `scalar_one_or_none()`. Duplicate fingerprints shouldn't exist, but when they did
    (real rows, 2026-08-13) `scalar_one_or_none()` raised `MultipleResultsFound` and
    aborted every subsequent run — a permanent poison pill. Merging into the oldest match
    is the same outcome dedup wants anyway.
  - Note a real-world case this correctly collapses: jobfound.org republishes the same
    role on different dates as separate listings with different slugs, different
    `posted_at`, and *materially different* content (one Fluence "Intern Engineer" pair
    differed on salary — `2-4 LPA` vs `10-20 LPA` — and description length). Same
    fingerprint, same apply URL, one real job. When cleaning such a pair up by hand,
    check both rows' contents first rather than assuming they're carbon copies.

**AI description rewriting** (`pipeline/rewriter.py`) — added to address a real
copyright/AdSense risk, not a nice-to-have: verbatim scraped `description_original` is
copyrighted by the source site/employer, and republishing it wire-for-wire also reads as
scraped/duplicate content to AdSense review. `pipeline/runner.py::_store()` calls
`DescriptionRewriter.rewrite()` on `description_original` and writes the result to
`rewritten_description` — but **only in the branch where `find_duplicate()` returned
None**, i.e. only for a job that's actually about to be inserted. A job that turns out to
be a duplicate is merged into the existing row (which already has, or will get, its own
rewrite) and is never re-sent to the AI — this is a deliberate cost control, not an
oversight.
  - This is the single integration point for the whole pipeline: adding a new source in
    `scrapers/sources/` gets rewriting for free, no per-source code.
  - Provider is Google Gemini's `generateContent` REST API, model `gemini-flash-latest`
    (a rolling alias, deliberately not a dated snapshot — verified live that dated
    snapshots get retired for new API keys on Google's own schedule: both
    `gemini-2.5-flash` and `gemini-2.5-flash-lite` 404 with "no longer available to new
    users" as of 2026-08-12 despite the `ListModels` endpoint still listing them),
    called directly over the `httpx` dependency already in `requirements.txt` — no
    `anthropic` SDK, no `google-generativeai` SDK, no new dependency at all. Auth is the
    API key as a `?key=` query param (the standard/most compatible auth method for this
    endpoint), not a header. Config lives in `config.py`/`.env` as
    `GEMINI_API_KEY`/`GEMINI_API_BASE`/`GEMINI_MODEL`/`GEMINI_THINKING_BUDGET` plus the
    provider-agnostic `REWRITE_ENABLED`/`REWRITE_TIMEOUT_SECONDS`/`REWRITE_MAX_RETRIES`/
    `REWRITE_MAX_CONCURRENCY`/`REWRITE_TEMPERATURE`.
  - `GEMINI_THINKING_BUDGET` defaults to `-1` — Gemini's "dynamic"/"Auto" thinking mode
    (per direct user instruction), where the model itself decides per-request how much
    internal reasoning a given description needs, rather than a fixed token budget being
    hardcoded here. `0` would disable thinking outright; a positive integer would pin an
    exact token budget — neither is currently used.
  - Never blocks storage and never raises: an empty/missing `description_original`, a
    disabled/unconfigured rewriter, or any API failure (timeout, 429/5xx after
    `rewrite_max_retries` retries, a non-retryable 4xx, an empty `candidates` list e.g.
    from a safety block, or a malformed response body) all just leave
    `rewritten_description=None` — the same "missing field, not an error" convention the
    rest of this pipeline uses. A stored row with `description_original` set but
    `rewritten_description` still `None` is safe to pick up later from a backfill script;
    nothing about this stage is stateful beyond that one column.
  - The system prompt (`_SYSTEM_PROMPT` in `pipeline/rewriter.py`) is the actual
    copyright-risk control and should not be loosened casually: meaning must not change
    (nothing added, nothing dropped), plain simple wording, no markdown/commentary in the
    output. Don't hand-wave this as "just call the AI" — the rules in the prompt are the
    whole point of this stage existing. It's passed via Gemini's `system_instruction`
    field, not folded into the `contents` array.
  - Verified live against the real Gemini API (not just against mocked tests in
    `tests/test_rewriter.py`): a real call with `gemini-flash-latest` against a sample
    software-engineer description returned a faithful, plain-language rewrite (same
    facts — years of experience, tech stack, degree requirement, salary, location — just
    reworded), confirming both the request shape (`system_instruction` +
    `thinkingConfig`) and the response-parsing path are correct end-to-end, not just
    against mocks. Re-verify with a fresh smoke test (call
    `default_rewriter.rewrite(...)` directly, same pattern as
    "Previewing scraper output without Postgres" below) before assuming a change here is
    safe — this is exactly how the `gemini-2.5-flash` 404 above was caught.

### Read API (Phase 3, `api/`)

The frontend-facing HTTP layer. Deliberately a separate FastAPI process from the
scraping pipeline, not folded into `jobs/scrape_all.py` or run alongside it — `api/`
only ever reads (shares `db/session.py`'s async engine/session factory read-only via
`api/deps.py::get_db`), the pipeline only ever writes; nothing bridges the two at
runtime. `scrapers/`, `pipeline/`, and `db/models.py` are all unaware this layer exists.

- **`api/schemas.py`'s `JobOut` is not a 1:1 passthrough of `JobModel`** — it's a
  distinct public shape, assembled field-by-field in `api/routers/jobs.py::_to_job_out`.
  Two things are deliberately hidden/derived, not just renamed:
  - `description_original` is **never** serialized directly — that's the copyrighted
    scraped text `pipeline/rewriter.py` exists to avoid republishing verbatim. The
    public `description` field is `rewritten_description or description_original`,
    computed at serialization time only; the stored `rewritten_description` column
    itself is untouched by this API (it never writes). `description_is_ai_rewritten`
    tells the caller which case it got, so the frontend can e.g. show a "draft
    description" badge instead of silently presenting scraped text as finished copy.
    This fallback exists specifically because AI rewriting is currently disabled (see
    above) — once `REWRITE_ENABLED=true` and a backfill has run, most rows will have a
    real rewrite and the fallback becomes mostly dormant, but it should stay in place
    rather than being removed, since a rewrite can still fail per-job going forward.
  - Internal-only fields are dropped entirely: `fingerprint`, `resolved_domain`,
    `external_id` — pipeline bookkeeping with no meaning to a frontend user.
- **No `is_external` filter is applied in `GET /jobs`**, on purpose, not an oversight —
  `pipeline/runner.py`'s architecture rule is that `is_external=False` rows are never
  persisted at all (see "Why the external-link filter runs twice" above), so every row
  in the table already satisfies `is_external=True` by construction. `is_active` *does*
  need filtering here (`include_inactive=False` by default) since `jobs/health_check.py`
  flips it independently of insert time, on its own schedule.
- **CORS is wide open** (`settings.cors_origins` defaults to `["*"]`, `config.py`) —
  deliberate for a public read-only API with no auth/cookies to protect, not an
  oversight. Narrow `CORS_ORIGINS` in `.env` to the real frontend origin(s) before this
  is ever deployed publicly; `"*"` is a local-dev convenience only.
- **Pagination is offset/limit** (`limit` default 20, max 100, `offset` default 0),
  returned alongside `total` so the frontend can build page controls without a second
  request. `GET /jobs` supports filtering by `source`, `location` (substring, case-
  insensitive), `employment_type`, `seniority`, `is_remote`, `has_salary`, `min_salary`,
  `tag` (exact match against the `tags` array via Postgres `ARRAY.contains`), and `q`
  (substring match against `title` or `company`); sortable by `posted_at` or
  `scraped_at`, either direction, nulls sorted last on descending / first on ascending.
- **Verified live against the real `job_aggregator` database** (not just imported and
  assumed correct): ran the server, hit `/health`, `/jobs` with several filter
  combinations, `/jobs/{id}` for both a hit and a 404, and specifically confirmed the
  `description`/`description_is_ai_rewritten` fallback returns `false` + raw original
  text for the 7 jobfound rows that failed AI rewriting during the quota-exhausted
  2026-08-13 run, and `true` + rewritten text for the other 10 — the fallback logic
  actually works against real mixed data, not just the happy path.

### Frontend (Phase 3, `frontend/`)

Next.js 16 (App Router) + React 19 + Tailwind v4 + TypeScript, scaffolded with
`create-next-app`. A **separate npm project** — its own `package.json`, `node_modules`,
`.gitignore`, and `.env.local`; nothing in the Python backend imports from it or vice
versa. They communicate over HTTP only, via `API_BASE_URL` (`frontend/.env.local`,
default `http://127.0.0.1:8000`).

- **Everything is a React Server Component; there is no client-side data fetching and no
  `"use client"` anywhere.** Pages call `frontend/lib/api.ts` on the server and ship
  rendered HTML. This is a deliberate SEO decision, not a style preference: job listings
  have to be indexable (and the whole AdSense angle in `pipeline/rewriter.py`'s rationale
  depends on this content ranking), and a client-fetched list is not. It also means the
  browser never learns the API's address. `cache: "no-store"` on every fetch, since the
  `jobs` table changes under it whenever `scrape_all`/`health_check` run.
- **All filter/sort/page state lives in the URL**, never in React state.
  `frontend/components/SearchFilters.tsx` is a plain `GET <form action="/">` whose field
  names are *exactly* the API's query-parameter names, so submitting produces a
  shareable, crawlable URL that `app/page.tsx` reads straight back out of `searchParams`.
  It works with JS disabled. `offset` is deliberately not a form field — changing a
  filter should reset to page 1, which happens naturally because the submitted URL omits
  it.
- **`params`/`searchParams` are Promises and must be awaited** — Next.js 16 removed the
  synchronous compatibility shim that 15 still had. `frontend/AGENTS.md` (auto-generated,
  and re-added by `next dev` if deleted) warns that this Next version differs from
  training data; the bundled docs at `frontend/node_modules/next/dist/docs/` are the
  authority, especially
  `01-app/02-guides/upgrading/version-16.md`. Check them before assuming an API shape.
- **The `description_is_ai_rewritten` flag is surfaced in the UI, not swallowed.** When
  it's false (AI rewriting is currently disabled — see above), the detail page renders a
  "shown as published by the employer or source site" note. That's the honest-labelling
  half of the same copyright concern `pipeline/rewriter.py` exists for; don't quietly
  drop it when rewriting is re-enabled, since individual rewrites can still fail.
- **Job detail pages emit `JobPosting` JSON-LD** (`app/jobs/[id]/page.tsx`) for Google
  Jobs eligibility. The payload is `JSON.stringify`'d with `<` escaped to `<` so a
  description containing `</script>` can't break out of the tag — descriptions are
  attacker-influenced (scraped) text, so this is a real escape, not ceremony.
- **Descriptions render as text nodes, never `dangerouslySetInnerHTML`.** Both the
  scrapers' HTML-stripping and the rewriter's "no markdown" system-prompt rule guarantee
  plain text; `lib/format.ts::toParagraphs` splits on newlines and `looksLikeHeading`
  applies heading styling heuristically (cosmetic only — a wrong guess never drops text).
- **URLs use the job's `id`** (a SHA-256 hash) — `/jobs/8ef8d94...`, not a readable slug
  like jobfound.org's `/job/produck-is-hiring-for-swe-intern-...`. That's a real SEO
  weakness worth fixing later, but it needs a `slug` column on `JobModel` + a migration +
  an API lookup path; don't fake it client-side.
- **Verified live end-to-end** against the real 17-row database, not just built: every
  filter's result count on the rendered page was cross-checked against the same query
  against the API directly (`/`, `employment_type`, `seniority`, `is_remote`, `location`,
  `has_salary`, `q` — all matched exactly), plus a detail page (200, with Apply/skills/
  similar-jobs/JSON-LD present) and an unknown id (404).

~~Known loose end: nested git repo at `frontend/.git`.~~ **Resolved.** The repo root is
now a git repo, `frontend/.git` is gone, and `frontend/` is tracked as ordinary files in
the root repo (31 files) rather than an accidental submodule.

### Source-format drift, and why `fetched=0` is ambiguous (2026-08-14 outage)

**Both sources silently stopped storing anything, and nothing looked broken.** Worth
reading before debugging "the scraper isn't finding jobs" — the whole failure took a day
to notice because every symptom pointed the wrong way.

`SourceRunStats.fetched` is `len(source.run())`, i.e. the count *after* normalize. So a
source whose `normalize()` throws on every record reports `fetched=0` — **byte-for-byte
identical to a genuinely quiet site**. There is no error, no crash, no non-zero exit, and
Railway shows a green successful deploy. Do not conclude "the site had nothing new" from
`fetched=0` alone; confirm against the live site first (see the preview scripts below).

Three distinct bugs, all with that same signature:

1. **talentd changed its JSON-LD field types** (fixed in `6a94e67`).
   `employmentType` went from `"full-time, remote"` (string) to `["FULL_TIME","INTERN"]`
   (array); `experienceRequirements` went from `"0-2 years"` (string) to schema.org's
   `{"@type":"OccupationalExperienceRequirements","monthsOfExperience":0}` (dict). Both
   raised `TypeError` out of `re.split()`/`re.search()` on *every* listing. Note the dict
   carries **months, not years** — convert before bucketing or a 24-month role becomes
   "lead". `normalize()` now accepts both shapes for both fields.
2. **jobfound dropped `www` from its canonical URLs** (fixed in `709fefb`).
   `_extract_sitemap_job_urls` hardcoded `https://www\.jobfound\.org/job/` and matched
   **0 of 2,216** live job URLs once the site canonicalized onto the apex domain — so
   `fetch()` returned an empty list without downloading a single page. Host is now
   matched with `www.` optional. `SITEMAP_URL` still points at the `www` host and is
   fine: it 301s to the apex and `follow_redirects=True` handles it.
3. **`find_duplicate()` was blind to rows added earlier in the same batch** (fixed in
   `709fefb`). `db/session.py` builds sessions with `autoflush=False`, so a pending
   `session.add()` is invisible to a later `SELECT`; two jobs sharing a fingerprint in one
   run each missed the other and both got inserted. Those rows then made
   `scalar_one_or_none()` raise `MultipleResultsFound` on every subsequent run — a
   permanent poison pill that aborted the whole scrape. Now `flush()`es first and reads
   the oldest match with `first()` instead of raising.

**The guard that hid all of this**: `BaseSource.run()` catches any exception from
`normalize()` and skips that record, so one bad listing can't sink a run. That guard is
correct and stays — but it now **logs** the exception (`logger.exception`), because a
`normalize()` failing on 100% of records must not be able to masquerade as an empty site
again. If a source reports `fetched=0`, check the logs for that line first.

**Lesson for future source work**: these sites change their payload shape without notice
and the failure is silent by construction. When a source goes quiet, re-verify the real
field types against a live page (a throwaway script that calls `fetch()`/`parse()` and
prints `type(v)` per field is the fastest path — that's how all three were found) before
assuming the site is just quiet.

### The `jobfound` source (`scrapers/sources/jobfound.py`)

Non-obvious design decisions, established by direct live-site inspection — don't
"simplify" these without re-verifying against the real site first:

- **Discovery is via `sitemap.xml`, not the `?page=N&loc=India` listing endpoint.** The
  listing page is client-rendered Next.js with zero job data in its raw HTML (data comes
  from a client-side API call under `/api/`, which was robots.txt-disallowed at the time
  this was built — the site's robots.txt has since changed to remove nearly all of its
  custom rules, but the listing page is *still* empty of data regardless of robots, so
  the sitemap approach stands on its own technical merits).
- **Sitemap `<loc>` URLs are on the apex domain, not `www`** (as of 2026-08-14 — they
  used to be `www`). `_extract_sitemap_job_urls` matches the host with `www.` optional so
  either form works; **never re-pin it to one host**. Getting this wrong returns zero
  URLs, which reads as "quiet site" rather than an error — see the outage section above.
  Covered by `test_sitemap_extraction_accepts_apex_and_www_hosts`.
- **Detail pages (`/job/{slug}`) are fully server-rendered** via Next.js React Server
  Components ("Flight") streaming — a JSON payload (`initialJob`) is embedded across
  multiple `self.__next_f.push([1,"..."])` script calls that must be reassembled. Two
  hard-won facts about that reassembly, both verified against production, not assumed:
  1. Consecutive Flight rows are **not** reliably newline-separated (a row can butt
     directly against the previous row's last byte with zero delimiter). A text row's
     content is only reliably delimited by its own declared `T<hex-byte-length>` prefix —
     `_resolve_flight_text_row` slices exact bytes, it does not split on `\n`.
  2. The `description` field is sometimes a `"$21"`-style reference to a separately
     streamed row, and sometimes literal inline HTML directly in `initialJob` — both
     shapes occur on real listings and must both be handled (`_extract_initial_job`).
- **Windowed to recent postings, not a fixed page count.** `fetch()` walks the sitemap
  in order (verified newest-first across the full ~1,780-URL range) and stops the first
  time it sees a posting older than `max_job_age_hours` (default 24) — so a run costs
  "however many jobs came in since last time," not a fixed number of pages.
  `safety_max_pages` (500) is only a circuit breaker for the case `postedAt` is
  unparseable across a long stretch, not the intended stopping condition. `parse()`
  re-checks the same cutoff independently (authoritative; `fetch()`'s stop is only an
  optimization) and also drops any job with no usable `postedAt` at all — recency can't
  be confirmed for something that can't be dated.
- **India-only filtering uses the `country` JSON field, not the URL slug.** The slug
  pattern (`{company}-is-hiring-for-{title}-...-india-{date}`) is inconsistent — plenty
  of genuine India postings omit the `-india-` suffix, and non-India ones can look
  equally generic.
- **Description text is taken as a whole**, not split into named sections. Section
  headers are completely free-form per employer (seen: "General Summary", "Who We Are",
  "Role Summary", as well as "Key Responsibilities"/"Requirements" on some but not most)
  — hunting for two specific header strings would silently lose content on most listings.
- A relative-time UI label like "1 day ago" on the live site means roughly 24–48h old,
  not "within a day" — don't use it as a proxy for the `max_job_age_hours` cutoff when
  eyeballing whether the scraper's output looks right against what's visible on-site.

### The `talentd` source (`scrapers/sources/talentd.py`)

Non-obvious design decisions, established by direct live-site inspection (robots.txt,
`/jobs/sitemap.xml`, the listing page, and real `/jobs/{slug}` detail pages) — don't
"simplify" these without re-verifying against the real site first:

- **Discovery is via the dedicated `https://www.talentd.in/jobs/sitemap.xml`**, not the
  400-page paginated `/jobs?page=N` listing. This sitemap (~4,027 `<url>` entries, each
  with a `<lastmod>`) is separate from the site's generic `/sitemap.xml` (which only
  lists static/category pages). Individual job-posting entries are verified sorted
  newest-first by `<lastmod>` (spot-checked positions 30-45, 500-505, and 2000-2005 —
  strictly decreasing). The first ~13 entries are category/city hub pages
  (`/jobs/it-software-jobs`, `/jobs/jobs-in-bangalore`, etc.) whose `<lastmod>` is always
  "now" (dynamically generated, not dated content) — they sort first regardless, but
  that's harmless: `parse()` drops them structurally (no `JobPosting` JSON-LD found), no
  hardcoded skip-count needed. `robots.txt` disallows `/api/` for generic user agents and
  several multi-filter `/jobs?...` combos (`?sort=`, `?batch=`, and 2-3-way combinations
  of `employment_type`/`role_category`/`city`/`job_type`) — this source never constructs
  any `/jobs?...` URL at all, so it's compliant by construction. No `Crawl-delay` is
  published, unlike jobfound.org's explicit one; `requests_per_minute`/
  `crawl_delay_seconds` (30/1.5) are set more conservatively than jobfound's (60/1.0) as
  a result, pending real-run evidence it's safe to tighten.
- **This source is software/IT-specific by product decision, not talentd.in's own
  scope.** The site itself covers many other categories — visible directly in its own
  `/jobs/sitemap.xml` hub-page entries: `it-software-jobs`, `core-engineering-jobs`,
  `banking-finance-jobs`, `bpo-customer-support-jobs`, `sales-marketing-jobs`,
  `hr-admin-jobs`, `design-jobs`, `healthcare-pharma-jobs`,
  `manufacturing-operations-jobs`, `research-science-jobs`, `government-defence-jobs`,
  `other-jobs`. No per-job JSON-LD field carries that category (confirmed: `JobPosting`
  has no `industry`/`occupationalCategory`/department field), so `parse()` infers scope
  from `title` + `skills` text against that same vocabulary via two module-level regexes:
  `_ROLE_EXCLUDE_RE` drops anything reading as BPO/customer support, sales/marketing, or
  HR/admin — checked *first* and wins even if a software word also appears (e.g.
  "Software Sales Executive" is a sales role, not an engineering one, and is dropped).
  `_ROLE_INCLUDE_RE` then requires an actual software/IT development signal (developer,
  engineer-with-a-tech-qualifier, SDE, QA/SDET, data engineer/scientist, DevOps, etc.) to
  keep a listing at all — a generic, signal-free title like "Associate Trainee" is
  dropped too, not just the three explicitly-named categories. Both lists are heuristic,
  not exhaustive (see `_is_software_related()` and the tests around it). Verified live:
  re-running the preview script against the same 24h window went from 14 kept jobs (incl.
  EY Analyst-Assurance, 4x Citi Securities & Derivatives Analyst, Genpact Business
  Analyst, Capgemini Non-Voice Customer Support, Kimberly-Clark Associate Trainee) down
  to 5 — Cisco/Emerson/KLA/Harman Software Engineer(ing) roles and a Deloitte Full Stack
  Development Executive.
- **Detail pages are Next.js App Router, RSC-streamed like jobfound, but the JobPosting
  JSON-LD is delivered as its own single, self-contained push chunk** — verified directly
  against a real captured page: decoding one `self.__next_f.push([1,"..."])` call (one
  level of JS string unescaping) yields a complete, directly-parseable JSON document
  (`{"@context":...,"@graph":[{"@type":"JobPosting",...},{"@type":"BreadcrumbList",...}]}`).
  Unlike jobfound's `initialJob`, no byte-length-prefixed row resolution or buffer
  concatenation across multiple pushes is needed here — a real, hands-on inspection
  disproved an initial assumption (carried over from jobfound's more complex format) that
  a second escaping layer would be involved.
- **The JSON-LD's own `description` field is a truncated SEO snippet, not the full job
  text.** The full description is separate, literal server-rendered HTML in a
  `<div class="jobContent_jobContent__{buildhash}">` block elsewhere in the page. The
  hash suffix is a CSS-module build artifact, not stable across deploys — match on the
  `jobContent_jobContent__` prefix, never the exact class name.
- **The real Apply destination is not the JSON-LD's `url` field** — that field is
  talentd.in's own canonical page URL for the posting. The actual apply link is a plain,
  unescaped `<a href="..." target="_blank" rel="noopener noreferrer">Apply Now</a>`
  elsewhere in the literal DOM, pointing straight at the hiring company's own ATS
  (verified: a Workday URL on a real Genpact posting). Using the JSON-LD `url` here would
  silently classify every listing as DIRECT instead of EXTERNAL — this was the single
  most important correctness point in this source, called out explicitly in the module
  docstring and covered by a dedicated regression test
  (`test_apply_url_is_dom_link_not_json_ld_canonical_url`).
- **`employmentType` arrives in two different shapes**, and both must keep working:
  a comma-separated multi-value string (`"full-time, remote"`, found live on a real
  Amazon "Virtual" listing) **and a JSON array** (`["FULL_TIME"]`,
  `["FULL_TIME","INTERN"]` — as of 2026-08-14 this is what the site actually sends).
  `normalize()` flattens an array to that same comma-separated string, then splits on
  `,`/`/` and maps each token independently, taking the first one that matches a
  canonical `employment_type` value; non-canonical descriptors like `"remote"` are
  skipped there but still folded into the `is_remote` heuristic. Mapping the whole string
  as one key (an earlier version of this code did this) produces a garbage compound value
  like `"full-time,-remote"`. Assuming it is always a string (an *even earlier* version)
  raised `TypeError` on every listing and silently killed the source — see the outage
  section above. Both shapes are covered by
  `test_employment_type_multi_value_string_picks_canonical_token` and
  `test_employment_type_json_array_is_handled`.
- **`experienceRequirements` is schema.org's `OccupationalExperienceRequirements` dict**
  (`{"@type":..., "monthsOfExperience": 0}`) as of 2026-08-14, not the free-form
  `"0-2 years"` string it used to be; `_infer_seniority()` handles both. The dict's value
  is in **months** — it's divided by 12 before bucketing, since reading it as years would
  file a 24-month role as `"lead"`. See
  `test_seniority_from_occupational_experience_requirements_dict`.
- **No structured remote-work field exists at all** (unlike jobfound's `workplaceType`)
  — `is_remote` is always an inferred guess from title/location/slug/employmentType text
  (`"hybrid"` explicitly overrides `"remote"`/`"virtual"` to `False`) and is therefore
  always recorded in `source_fields_missing`, regardless of which way the heuristic lands.
- **India scope**: `jobLocation[0].address.addressCountry` was `"IN"` on every sample
  checked and the site's whole navigation is India-city-based, so talentd.in appears
  India-specific by construction. `parse()` still drops a listing if that field is
  present and *not* `"IN"`, but does **not** drop one just because the field is absent —
  absence isn't evidence of being non-Indian on this source.
- **`employment_type` values beyond `"full-time"` are unconfirmed.** Only `"full-time"`
  has been observed on a real listing; the mapping table's internship/part-time/contract
  entries are best-effort guesses at likely schema.org-style values and are commented as
  such in the code (`_EMPLOYMENT_TYPE_MAP`) — revisit once real postings of those types
  have been sampled.

## Previewing scraper output without Postgres

`_preview_scraper_output.py` (jobfound), `_preview_talentd_output.py` (talentd), and
`_diagnose_*.py` in the repo root are throwaway, gitignore-worthy diagnostic scripts (not
part of the shipped architecture — nothing under `scrapers/`, `pipeline/`, `db/`, or
`jobs/` depends on them). They run the real pipeline stages by importing
`pipeline.runner`'s private helpers (`_finalize_job`, `_resolve_urls`) directly, stopping
short of the DB-write step, and dump results to `scraper_output.json` /
`scraper_output_talentd.json` respectively (deliberately distinct filenames so the two
don't clobber each other). Useful pattern for verifying a source end-to-end before
Postgres is wired up; recreate similarly for each new source if these get cleaned up.
