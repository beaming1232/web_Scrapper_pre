# Deployment Checklist

Working checklist for taking this project from "runs on my machine" to a real,
public website. Grouped by what breaks first. Check items off as you go —
nothing here has been done yet unless marked otherwise.

Verified against the actual project state on 2026-08-13 (not assumed):
no git repo at project root, `frontend/.git` exists as a stray nested repo,
`/sitemap.xml` and `/robots.txt` both 404, default Next.js favicon/placeholder
SVGs still in `frontend/public/`, `cors_origins` defaults to `["*"]`,
no About/Privacy/Terms pages exist, and `AsyncIOScheduler` is only mentioned
in a docstring — nothing actually schedules `scrape_all`/`health_check` yet.

---

## 1. Database — the big one you already suspected ✅ DONE (2026-08-13)

- [x] **Move off the local Postgres.** Now on **Neon** (hosted, `ap-...neon.tech`
  region `us-east-2`). `DATABASE_URL` updated in `.env`. Note for future
  reference: Neon's copy-paste string uses `sslmode=require`, which
  **does not work with asyncpg** (`TypeError: unexpected keyword argument
  'sslmode'`, confirmed by testing) — had to change it to `ssl=require`,
  and drop `channel_binding=require` (not a recognized asyncpg param).
- [x] **Ran `alembic upgrade head` against Neon** — `jobs` table created,
  30 columns, confirmed matching `db/models.py::JobModel` exactly.
- [x] **Decided: started fresh**, did not migrate the old local rows. Ran
  `python -m jobs.scrape_all` directly against Neon — 20 real jobs inserted.
  Local Postgres is no longer used by the project at all (the Windows
  service itself is still installed/running on this machine, just unused —
  left alone deliberately, stopping it is a system-level action outside
  project scope).
- [x] Connection pooling checked: the Neon string uses its `-pooler`
  (PgBouncer) endpoint. Stress-tested 8 repeated queries across separate
  sessions — no prepared-statement errors, safe for this app's usage
  pattern. Not yet checked: Neon's actual free-tier connection cap number
  against `DB_POOL_SIZE=5` + `DB_MAX_OVERFLOW=10` — hasn't been a problem
  at current (very low) traffic, but worth a real check before assuming it
  holds under production load.

## 2. Backend API (`api/`) needs a real host

- [ ] `uvicorn api.main:app` on your machine isn't a deployment — it stops
  the moment your terminal closes. Pick a host that keeps a Python process
  running: **Railway**, **Render**, or **Fly.io** are the common choices for
  a small FastAPI + Postgres app like this.
- [ ] **Lock down CORS.** `config.py`'s `cors_origins` defaults to `["*"]` —
  deliberately, for local dev. Before this is public, set `CORS_ORIGINS` to
  the real frontend domain only, e.g. `["https://yourdomain.com"]`.
- [ ] Set every backend env var on the hosting platform (not in a committed
  file): `DATABASE_URL`, `GEMINI_API_KEY`, `CORS_ORIGINS`, `REWRITE_ENABLED`,
  etc. — see `.env.example` for the full list.
- [ ] Confirm the host's Python version is 3.11+ (per `CLAUDE.md`).

## 3. Frontend (`frontend/`) needs a real host

- [ ] **Vercel** is the natural fit (it's the company behind Next.js, and
  this app already uses App Router server components) — but Netlify or
  similar work too.
- [ ] Set `API_BASE_URL` on the hosting platform to the **deployed** backend
  URL, not `http://127.0.0.1:8000`. Right now `frontend/.env.local` only
  exists locally and isn't deployed with the app (it's gitignored, and
  should stay that way — this env var is the exception below).
- [ ] Re-run `npm run build` after any last-minute change — it both
  type-checks and catches build errors the dev server won't.

## 4. Git — you don't actually have a repo yet

- [ ] **The project root is not a git repository at all** (confirmed:
  `git status` fails with "not a git repository"). Every deploy platform
  above deploys *from* git — you need `git init` at the project root before
  any of this works.
- [ ] `frontend/.git` exists as a **stray nested repo** (created by
  `create-next-app`, flagged back when it was scaffolded). If you `git init`
  the root now, this becomes an accidental submodule. **Delete
  `frontend/.git` first**, then `git init` at the root so `frontend/` is
  tracked as normal files in the same repo.
- [ ] Double check `.gitignore` actually excludes `.env` (root) and
  `frontend/.env.local` before your first commit — both currently hold real
  secrets (Gemini key, DB password). One accidental `git add .` before
  `.gitignore` is right, and those are in your history forever.

## 5. SEO basics — currently missing, confirmed by curl

- [ ] `/sitemap.xml` → **404 right now**. Needed for jobs to get indexed by
  Google at all. Next.js supports a `app/sitemap.ts` file that can query the
  API and generate this automatically — straightforward to add, not built
  yet.
- [ ] `/robots.txt` → **404 right now**. Add `app/robots.ts` (allow
  everything, point at the sitemap).
- [ ] **Favicon is still the default Next.js icon**, and `frontend/public/`
  still has the default placeholder SVGs (`vercel.svg`, `next.svg`, etc.)
  from `create-next-app` — nothing project-specific has replaced them yet.
- [ ] No Open Graph / social-share preview image — job links shared on
  WhatsApp/Twitter/LinkedIn will show a blank/generic preview.

## 6. Pages that don't exist yet — and matter for more than just looks

- [ ] **No About, Privacy Policy, Terms of Service, or Contact page exist.**
  Confirmed — `frontend/app` only has the homepage and `jobs/[id]`. This
  isn't just polish: **Google AdSense requires these pages to even apply**,
  and monetization is the stated reason `pipeline/rewriter.py`'s whole AI
  rewrite stage exists in the first place. If AdSense is part of the plan,
  this blocks that, not just "looks unfinished."
- [ ] `app/not-found.tsx` and the inline API-error states exist; `loading.tsx`
  and a top-level `error.tsx` for unexpected crashes do not (flagged
  earlier, still true) — worth adding so a real error doesn't show Next's
  raw default error screen to a visitor.

## 7. Content freshness — nothing runs on a schedule yet

- [ ] Confirmed: **no scheduler is wired up anywhere.** `AsyncIOScheduler`
  is only mentioned in `jobs/scrape_all.py`'s module docstring as an
  example of how you *could* wire it — nothing in the codebase actually
  calls it. Right now new jobs only appear when you manually run
  `python -m jobs.scrape_all`.
- [ ] Decide how scraping runs in production:
  - Wire up `AsyncIOScheduler` inside a long-running process on your backend
    host, **or**
  - Use the hosting platform's own cron/scheduled-job feature (Railway,
    Render, and most others have one) to run `python -m jobs.scrape_all`
    and `python -m jobs.health_check` on a schedule — probably simpler than
    managing a scheduler process yourself.
  - `config.py` already has `SCRAPE_CRON_SCHEDULE` / `HEALTH_CHECK_CRON_SCHEDULE`
    settings sitting ready for whichever approach you pick.
- [ ] Without this, the live site's job list goes stale the day after launch
  and never updates again on its own.

## 8. AI rewriting — a decision to make consciously, not by default

- [ ] `REWRITE_ENABLED=false` right now (no paid Gemini plan). Before going
  live, decide on purpose: get a paid/higher-quota Gemini key and flip it
  on, or launch with it off. Going live with it off means every job shows
  raw scraped text — which is precisely the copyright/AdSense risk the
  whole rewriter module exists to avoid (see `pipeline/rewriter.py`'s
  docstring). Not a blocker to launch, but shouldn't happen silently either.
- [ ] If/when you do flip it on, run a backfill pass for the jobs already
  stored with `rewritten_description = NULL` — there's no backfill script
  yet, only the convention that it's safe to write one later.

## 9. API has zero abuse protection right now

- [ ] `GET /jobs` and `GET /jobs/{id}` are fully public with no rate
  limiting, no API key, nothing. Fine for local dev; once the URL is public,
  anything (a scraper, a bot, a misbehaving script) can hammer it and your
  hosted Postgres connection pool along with it. Worth adding basic rate
  limiting before or shortly after launch — not necessarily before, but
  don't forget it.

## 10. Costs to actually check, not assume are free

- [ ] Hosted Postgres (free tiers exist but have limits — check row/storage/
  connection caps).
- [ ] Backend + frontend hosting (both often free at this traffic level, but
  confirm the specific platform's free-tier terms).
- [ ] A paid Gemini plan, if you enable rewriting (this was the free tier's
  429 quota issue from before).
- [ ] A domain name, if you want something other than the host's default
  subdomain (e.g. `yourapp.vercel.app`).

---

## Suggested order

1. Git repo sorted (section 4) — everything else deploys from this.
2. Hosted Postgres + migration (section 1).
3. Backend deployed, pointed at hosted Postgres (section 2).
4. Frontend deployed, pointed at deployed backend (section 3).
5. Sitemap/robots/favicon + legal pages (sections 5–6) before announcing it
   publicly or submitting to Google/AdSense.
6. Scheduler for ongoing scraping (section 7) so it doesn't go stale on day 2.
7. AI rewrite decision + rate limiting (sections 8–9) — can trail slightly
   behind initial launch but shouldn't be forgotten.
