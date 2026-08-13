# India Job Aggregator — Backend (Phase 1)

A modular job-scraping pipeline for Indian job boards. Phase 1 is backend
only: scrape → normalize → filter (external apply links only) → resolve
apply URLs → dedup → store in Postgres. No frontend, no API, no AI
description rewriting (that's a later, separate phase).

## Architecture at a glance

```
scrapers/sources/{name}.py  -> subclasses BaseSource, one file per site
        │  fetch() / parse() / normalize()
        ▼
scrapers/registry.py        -> auto-discovers every source, no manual wiring
        ▼
pipeline/runner.py          -> fetch → parse → normalize → filter_external
                                → resolve_url → dedup → store
        │
        ├─ pipeline/filter.py     external-apply-link hard filter
        ├─ pipeline/resolver.py   HEAD-based redirect resolution + cache
        ├─ pipeline/dedup.py      fingerprint + domain dedup/merge
        └─ pipeline/salary_parser.py  Indian salary string -> min/max/period
        ▼
db/models.py (JobSchema validation, JobModel ORM) -> Postgres `jobs` table
```

**Adding a new source = adding one file** in `scrapers/sources/` that
subclasses `BaseSource`. Nothing else needs to change — the registry
finds it automatically and the pipeline runs it identically to every
other source.

## Setup

1. **Python 3.11+** and a running **PostgreSQL** instance.

2. Create a virtualenv and install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your real `DATABASE_URL`
   (must use the `postgresql+asyncpg://` scheme) and any other overrides.

4. Create the database, then run migrations:
   ```
   alembic upgrade head
   ```

5. Run the salary parser tests to confirm the environment is set up
   correctly:
   ```
   pytest tests/ -q
   ```

## Running the pipeline

There are no sources registered yet in this phase (`scrapers/sources/`
is intentionally empty aside from `.gitkeep`) — `jobs/scrape_all.py` will
run zero sources until the first scraper is added.

```
python -m jobs.scrape_all      # runs every registered source once
python -m jobs.health_check    # HEAD-checks all active apply_urls, deactivates dead links
```

Both are meant to be triggered by cron / a process scheduler (e.g.
APScheduler, per `config.settings.scrape_cron_schedule` /
`health_check_cron_schedule`) — they run independently of each other.

## Adding a new source (later phase, for reference)

```python
# scrapers/sources/example_board.py
from scrapers.base import BaseSource

class ExampleBoardSource(BaseSource):
    source_name = "example_board"
    requests_per_minute = 15
    crawl_delay_seconds = 2.0

    async def fetch(self):
        ...  # httpx calls only, return raw payload(s)

    def parse(self, raw):
        ...  # raw payload -> list[dict] of loosely-structured records

    def normalize(self, raw_record):
        ...  # raw record -> canonical dict (see db.models.JobSchema)
             # never raise on a missing field; fill source_fields_missing
```

That's the entire integration surface. `scrapers/registry.py` picks it
up automatically the next time `discover_sources()` runs.

## Canonical job schema

See `db/models.py::JobSchema` for the full, authoritative field list and
defaults, and `db/models.py::JobModel` for the matching Postgres table.
Only `title`, `company`, `source`, and `raw_apply_url` are required —
every other field defaults to `None` / `False` / `[]` when a source
doesn't provide it. A missing field is never an error.

Key invariants enforced by the pipeline (not by individual scrapers):
- **External-only**: only jobs classified `apply_type=EXTERNAL` survive
  `pipeline/filter.py`; `is_external` is stamped there, never by a scraper.
- **Salary**: never store placeholder strings ("Not disclosed",
  "Negotiable") as if they were data — see `pipeline/salary_parser.py`.
- **Dedup**: primary key is `fingerprint` (slugified title+company+location);
  secondary is `resolved_domain` + apply URL path. Duplicates are merged
  (scraped_at bumped, source recorded in `merged_sources`), never
  re-inserted.
- **URL resolution**: HEAD request, single redirect hop, 5s timeout,
  cached per `raw_apply_url` for the process lifetime.

## Out of scope for this phase

- Frontend / UI
- API endpoints

Scraped descriptions are rewritten by DeepSeek before storage
(`pipeline/rewriter.py`) — see CLAUDE.md's "AI description rewriting" section for
the details (why, how it's wired in, and its config in `.env`).

## Project layout

```
scrapers/
  base.py             BaseSource abstract class (fetch/parse/normalize contract)
  registry.py         Auto-discovers BaseSource subclasses in sources/
  sources/            One file per job source (empty in this phase)
pipeline/
  runner.py           Orchestrates fetch→normalize→filter→resolve→dedup→store
  filter.py           External-apply-link hard filter
  resolver.py         HEAD-based redirect resolution + caching
  dedup.py            Fingerprint + domain dedup/merge logic
  salary_parser.py    Indian salary string parser (LPA, lakhs, k/month, etc.)
db/
  models.py           JobSchema (Pydantic canonical schema) + JobModel (ORM)
  session.py          Async SQLAlchemy engine/session factory
  migrations/         Alembic environment + versioned migrations
jobs/
  scrape_all.py       Cron entry point: run every registered source once
  health_check.py     Cron entry point: deactivate dead apply_urls
tests/
  test_salary_parser.py
config.py             pydantic-settings configuration (reads .env)
.env.example          All required environment variables, documented
requirements.txt      Pinned dependencies
alembic.ini           Alembic configuration
```
