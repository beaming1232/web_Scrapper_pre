"""
Apply URL resolution.

Many sources link through a tracking/redirect URL rather than the hiring
company's actual application page. This module follows that redirect
exactly once via a HEAD request (no body download) and records where it
actually lands.

Rules enforced here:
- HEAD request only (no body downloaded at any hop).
- Multi-hop: some sources (e.g. jobfound — see scrapers/sources/jobfound.py)
  are themselves aggregators, so their apply link can bounce through a
  tracker before reaching an ATS, which can itself redirect once more
  (Workday/Greenhouse/Oracle HCM tenants do this fairly often). We follow
  up to MAX_REDIRECT_HOPS hops via httpx's `follow_redirects=True` +
  `max_redirects=` — httpx handles the chain internally and still protects
  against redirect loops (raises TooManyRedirects past the cap, which we
  treat like any other resolution failure). Only the final Location is
  kept; intermediate hops are not recorded.
- Timeout: 5 seconds per request (config.settings.url_resolve_timeout_seconds)
  — since each hop is a separate underlying HTTP request, a full chain can
  take up to MAX_REDIRECT_HOPS x that timeout in the worst case. On timeout
  or any request error at any hop: leave `apply_url` as None and keep
  `raw_apply_url` as the value to fall back on.
- Every raw_apply_url is resolved at most once, ever — results (including
  failures) are cached so repeated jobs referencing the same apply link
  don't trigger repeat network calls.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from yarl import URL

from config import settings


# Max redirect hops followed when resolving a raw apply URL. 1 covers a
# plain tracker link; sources that themselves aggregate (tracker -> ATS ->
# ATS tenant redirect) need up to 3.
MAX_REDIRECT_HOPS = 3


@dataclass(frozen=True)
class ResolvedUrl:
    apply_url: str | None
    resolved_domain: str | None


class UrlResolver:
    """Resolves and caches raw apply URLs -> final (apply_url, domain).

    One instance is expected to live for the duration of a pipeline run
    (or longer, if the caller wires it up as a singleton) so the in-memory
    cache is actually useful. For persistence across process restarts,
    back this with a DB/Redis-backed cache instead — the interface here
    (`resolve`) is the only thing callers depend on.
    """

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self._timeout = timeout_seconds or settings.url_resolve_timeout_seconds
        self._cache: dict[str, ResolvedUrl] = {}

    async def resolve(self, raw_apply_url: str) -> ResolvedUrl:
        """Resolve one raw apply URL, using the cache if already resolved.

        Never raises: any transport error or timeout results in a cached
        ResolvedUrl(apply_url=None, resolved_domain=None).
        """
        if not raw_apply_url:
            return ResolvedUrl(apply_url=None, resolved_domain=None)

        if raw_apply_url in self._cache:
            return self._cache[raw_apply_url]

        result = await self._resolve_uncached(raw_apply_url)
        self._cache[raw_apply_url] = result
        return result

    async def _resolve_uncached(self, raw_apply_url: str) -> ResolvedUrl:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECT_HOPS,
                timeout=self._timeout,
            ) as client:
                response = await client.head(raw_apply_url)
                final_url = str(response.url)
        except (httpx.TimeoutException, httpx.RequestError, httpx.TooManyRedirects):
            return ResolvedUrl(apply_url=None, resolved_domain=None)

        domain = URL(final_url).host
        return ResolvedUrl(apply_url=final_url, resolved_domain=domain)

    def cache_size(self) -> int:
        return len(self._cache)


# Process-wide singleton so pipeline stages sharing a run also share the
# resolution cache without needing to pass the resolver around explicitly.
default_resolver = UrlResolver()
