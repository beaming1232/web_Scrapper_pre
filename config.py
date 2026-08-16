"""
Application configuration.

All runtime configuration is loaded from environment variables (optionally via
a local .env file — see .env.example for the full list of variables). Nothing
in this module hits the network or the database; it only defines and validates
settings.

Usage:
    from config import settings
    settings.database_url
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central app settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database -----------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/job_aggregator",
        description="Async SQLAlchemy connection string (asyncpg driver).",
    )
    db_echo: bool = Field(default=False, description="Log all SQL statements (debug only).")
    db_pool_size: int = Field(default=5, description="SQLAlchemy connection pool size.")
    db_max_overflow: int = Field(default=10, description="SQLAlchemy pool overflow size.")
    # The DB is hosted (Neon) and reached over the public internet, so every
    # setting below exists to bound how long a network problem can hang a
    # request. Without them a refused/hung connection propagates as an
    # unbounded wait or a bare 500 - see api/routers/health.py's docstring.
    db_pool_recycle_seconds: int = Field(
        default=300,
        description="Discard pooled connections older than this. Neon's PgBouncer "
        "endpoint drops idle server-side connections, and a pooled connection that "
        "died that way otherwise surfaces as a mid-request error.",
    )
    db_pool_timeout_seconds: float = Field(
        default=10.0, description="Max wait for a free connection from the pool."
    )
    db_connect_timeout_seconds: float = Field(
        default=30.0,
        description="Max time to establish a new asyncpg connection. Neon scales "
        "compute to zero when idle, so a cold connect is slow but should still be "
        "bounded rather than open-ended. Measured >5s (and near 10s) on a real cold "
        "start, so this is deliberately generous - it exists to stop an indefinite "
        "hang, not to fail fast.",
    )
    db_command_timeout_seconds: float = Field(
        default=30.0, description="Max time for a single asyncpg statement to run."
    )

    # --- Scraping / networking -----------------------------------------
    request_timeout_seconds: float = Field(
        default=15.0, description="Default httpx request timeout for fetch()."
    )
    url_resolve_timeout_seconds: float = Field(
        default=5.0, description="Timeout for HEAD-based apply URL redirect resolution."
    )
    default_requests_per_minute: int = Field(
        default=20, description="Fallback rate limit when a source doesn't override it."
    )
    default_crawl_delay_seconds: float = Field(
        default=1.0, description="Fallback delay between requests when a source doesn't override it."
    )
    user_agents: list[str] = Field(
        default=[
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ],
        description="Pool of User-Agent strings rotated between requests.",
    )

    # --- AI description rewriting (Phase 2) -------------------------------
    # Scraped description_original is copyrighted content owned by the
    # source site / hiring company. pipeline/rewriter.py rewrites it via
    # Gemini before storage; gemini_api_key empty disables the whole
    # stage (jobs still get stored, just with rewritten_description=None).
    gemini_api_key: str = Field(
        default="", description="Gemini API key. Empty disables AI rewriting entirely."
    )
    gemini_api_base: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        description="Gemini API base URL.",
    )
    gemini_model: str = Field(
        default="gemini-flash-latest",
        description="Gemini model id. Uses the rolling '-latest' alias, not a dated "
        "snapshot — dated snapshots (e.g. gemini-2.5-flash) get retired for new API "
        "keys on Google's own schedule, verified live: both gemini-2.5-flash and "
        "gemini-2.5-flash-lite 404 with 'no longer available to new users' as of "
        "2026-08-12 despite still being listed by the ListModels endpoint.",
    )
    gemini_thinking_budget: int = Field(
        default=-1,
        description="Gemini thinkingConfig.thinkingBudget. -1 = dynamic/auto thinking "
        "(model decides how much to reason per request); 0 disables thinking.",
    )
    rewrite_enabled: bool = Field(
        default=True, description="Master on/off switch for the rewrite pipeline stage."
    )
    rewrite_timeout_seconds: float = Field(
        default=30.0, description="Timeout per DeepSeek chat-completion request."
    )
    rewrite_max_retries: int = Field(
        default=2, description="Retries on timeout/429/5xx before giving up on one description."
    )
    rewrite_max_concurrency: int = Field(
        default=3, description="Max in-flight DeepSeek requests at once, process-wide."
    )
    rewrite_temperature: float = Field(
        default=0.3, description="Low temperature keeps the rewrite faithful to source meaning."
    )

    # --- API (frontend-facing read layer, api/) ---------------------------
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins for the read-only API. '*' is fine for "
        "local dev (the API has no auth/cookies for a wildcard to leak); narrow "
        "this to the real frontend origin(s) - e.g. "
        '[\"https://yourdomain.com\"] - before deploying publicly.',
    )

    # --- Social digest (social/, GET /social/digest) -----------------------
    site_base_url: str = Field(
        default="https://web-scrapper-pre.vercel.app",
        description="Public site URL that social posts link to. Not hardcoded because "
        "the site is on a .vercel.app subdomain for now (no domain budget yet) and must "
        "move to a real domain later - AdSense will not approve a subdomain owned by "
        "someone else. Changing this one value has to be enough to switch every post.",
    )
    social_digest_hours: float = Field(
        default=24.0,
        description="How far back GET /social/digest looks for jobs to announce. "
        "Independent of the scrapers' own max_job_age_hours: this is 'what have we "
        "stored recently worth posting about', not 'how far back should we scrape'.",
    )
    social_digest_max_jobs: int = Field(
        default=5,
        description="Most job titles to list in one post. The real cap is X's 280-char "
        "budget (social/digest.py trims to fit); this just bounds it before that.",
    )
    health_db_probe_timeout_seconds: float = Field(
        default=15.0,
        description="Max time /health and /health/db spend probing Postgres before "
        "reporting it unreachable. Bounds the healthcheck so a hung connection "
        "cannot stall it until Railway's healthcheckTimeout expires. Sits between "
        "a real Neon cold start (measured >5s) and railway.json's healthcheckTimeout "
        "(120s), so a merely-cold database reports 'connected' rather than being "
        "misreported as down.",
    )

    # --- Scheduler -------------------------------------------------------
    scrape_cron_schedule: str = Field(
        default="0 */6 * * *", description="Cron expression for the scrape_all job."
    )
    health_check_cron_schedule: str = Field(
        default="0 3 * * *", description="Cron expression for the link health checker."
    )

    # --- Misc --------------------------------------------------------------
    log_level: str = Field(default="INFO", description="Python logging level.")
    environment: str = Field(default="development", description="development | staging | production.")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()


settings = get_settings()
