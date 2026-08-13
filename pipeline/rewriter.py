"""
AI-based job description rewriting (Phase 2).

Scraped `description_original` text is copyrighted content owned by the
source site / hiring company, not us. Storing and displaying it verbatim
is a copyright risk, and it also means postings read as visibly identical
wire-for-wire copies of another site — exactly the "scraped/duplicate
content" pattern AdSense policy flags, not original editorial content.
Every job gets its description rewritten by an LLM before storage to
address both problems: meaning must survive intact, wording must not.

This module is deliberately the *only* place that knows about the AI
provider. `pipeline/runner.py` calls `default_rewriter.rewrite(...)`
exactly once per genuinely new (non-duplicate) job, right before it's
inserted — see that call site for why dedup merges skip this step (no
point paying for a rewrite of a row that already has one). Because the
integration point is the pipeline, not any individual scraper, adding a
new source in `scrapers/sources/` gets rewriting for free with zero
changes here or anywhere else — that's the scalability property this was
built for.

Provider: Google's Gemini `generateContent` REST API, called directly over
the httpx client already in requirements.txt — no separate SDK dependency.
Swapping providers later means changing this module's request-building
only; `rewrite()` is the only method the rest of the pipeline depends on.
Model is `gemini-flash-latest` (a rolling alias, not a dated snapshot —
dated snapshots get retired for new API keys on Google's own schedule;
verified live) with `thinkingConfig.thinkingBudget=-1` ("dynamic"/"Auto"
thinking in Gemini's own terms) — the model decides for itself, per
request, how much internal reasoning a given description needs rather
than us hardcoding a fixed budget.

Rules enforced via the system prompt below (don't loosen without checking
the copyright/AdSense risk tradeoff first):
  1. Meaning must not change — nothing added, nothing dropped.
  2. Nothing invented that wasn't in the source text.
  3. Plain, simple wording — a rewrite for clarity, not for marketing
     flourish.

Never raises and never blocks a job from being stored: any failure
(no API key configured, timeout, non-2xx, malformed response) is logged
and results in `rewritten_description=None`, the same way a missing
scraped field is handled elsewhere in this pipeline. A stored job with
`description_original` set but `rewritten_description` still None is
safe to retry later (e.g. a backfill script re-querying for that exact
condition) — nothing here is stateful beyond that one column.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You rewrite job posting descriptions for a job listing website. "
    "Rewrite the text the user gives you in clear, simple, plain language. "
    "Rules you must follow exactly:\n"
    "1. Do not change the meaning. Every requirement, responsibility, "
    "qualification, and fact in the original must still be present.\n"
    "2. Do not add anything that is not in the original text - no new "
    "duties, perks, requirements, claims, or filler sentences.\n"
    "3. Do not remove any substantive information, only reword it.\n"
    "4. Output only the rewritten description text itself - no preamble, "
    "no headings you invented, no commentary, no markdown formatting.\n"
    "5. Keep the overall length roughly similar; this is a rewrite, not a "
    "summary."
)


class _RetryableStatus(Exception):
    """Internal signal: HTTP error worth retrying (429 / 5xx)."""


class _NonRetryableStatus(Exception):
    """Internal signal: HTTP error not worth retrying (other 4xx, or a
    response body that doesn't parse the way we expect)."""


class DescriptionRewriter:
    """Rewrites one description at a time via Gemini, with bounded
    concurrency shared across a whole pipeline run (or process, if used
    as the module-level singleton below).
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        max_concurrency: int | None = None,
        temperature: float | None = None,
        thinking_budget: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = settings.gemini_api_key if api_key is None else api_key
        self._api_base = (api_base or settings.gemini_api_base).rstrip("/")
        self._model = model or settings.gemini_model
        self._timeout = settings.rewrite_timeout_seconds if timeout_seconds is None else timeout_seconds
        self._max_retries = settings.rewrite_max_retries if max_retries is None else max_retries
        self._temperature = settings.rewrite_temperature if temperature is None else temperature
        self._thinking_budget = (
            settings.gemini_thinking_budget if thinking_budget is None else thinking_budget
        )
        self._semaphore = asyncio.Semaphore(max_concurrency or settings.rewrite_max_concurrency)
        # Only used by tests to inject a fake transport; production always
        # uses httpx's real network transport (leaving this None).
        self._transport = transport

    @property
    def enabled(self) -> bool:
        """False when there's no API key configured or the master switch
        is off — callers treat that as "skip rewriting", not an error."""
        return bool(self._api_key) and settings.rewrite_enabled

    async def rewrite(self, description_original: str | None) -> str | None:
        """Rewrite one description. Never raises: returns None if there's
        nothing to rewrite, rewriting is disabled, or the call fails after
        retries."""
        if not description_original or not description_original.strip():
            return None
        if not self.enabled:
            return None

        async with self._semaphore:
            return await self._call_with_retries(description_original)

    async def _call_with_retries(self, text: str) -> str | None:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._call_once(text)
            except (httpx.TimeoutException, httpx.RequestError, _RetryableStatus) as exc:
                last_error = exc
            except _NonRetryableStatus as exc:
                logger.warning("Gemini rewrite failed (non-retryable): %s", exc)
                return None
            if attempt < self._max_retries:
                await asyncio.sleep(2**attempt)
        logger.warning(
            "Gemini rewrite failed after %d attempt(s): %s", self._max_retries + 1, last_error
        )
        return None

    async def _call_once(self, text: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(
                f"{self._api_base}/models/{self._model}:generateContent",
                params={"key": self._api_key},
                json={
                    "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": text}]}],
                    "generationConfig": {
                        "temperature": self._temperature,
                        "thinkingConfig": {"thinkingBudget": self._thinking_budget},
                    },
                },
            )

        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus(f"HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code >= 400:
            raise _NonRetryableStatus(f"HTTP {response.status_code}: {response.text[:200]}")

        try:
            data = response.json()
            candidates = data["candidates"]
            if not candidates:
                block_reason = data.get("promptFeedback", {}).get("blockReason")
                raise _NonRetryableStatus(f"No candidates returned (blockReason={block_reason})")
            parts = candidates[0]["content"]["parts"]
            content = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise _NonRetryableStatus(f"Unexpected response shape: {exc}") from exc

        content = content.strip()
        if not content:
            raise _NonRetryableStatus("Empty rewrite returned")
        return content


# Process-wide singleton, mirroring pipeline/resolver.py's default_resolver
# pattern — pipeline stages sharing a run share one bounded-concurrency
# rewriter without the caller having to wire it through explicitly.
default_rewriter = DescriptionRewriter()
