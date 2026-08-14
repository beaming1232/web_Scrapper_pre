"""
Jobfound (jobfound.org) source.

Jobfound is itself a job aggregator covering multiple countries. Findings
from manual inspection (see conversation history / commit message for the
full Step-1 report) that shape everything below:

1. The listing page (`/?page=N&loc=India`) is a client-rendered Next.js
   page with NO job data in the raw HTML, and its query-string form is
   explicitly disallowed by robots.txt (`Disallow: /*?*`) anyway. We do
   not use it.

2. `https://www.jobfound.org/sitemap.xml` (robots.txt's declared "Main
   sitemap") lists every `/job/{slug}` detail URL — ~1,770 at inspection
   time, across every country Jobfound covers, not just India. `/job/*`
   is explicitly `Allow`ed by robots.txt and carries no query string.

3. `/job/{slug}` pages ARE fully server-rendered: Next.js streams a
   React Server Components ("Flight") payload embedding one big
   `initialJob` JSON object per posting (title, company, salary, apply
   URL, ISO posted-at timestamp, etc.) plus the full job-description HTML
   as a separately-referenced text chunk. We parse that payload directly
   instead of scraping rendered HTML/CSS selectors — it's both more
   reliable and is exactly what the page itself renders from.

4. The "apply" mechanism is not a same-page icon to disambiguate: the
   page's Apply button uses the `applyUrl` field from that JSON directly.
   In every sample checked it was already a fully-qualified URL (no
   jobfound.org-hosted tracker wrapper observed) — usually the hiring
   company's own careers page or ATS (Greenhouse, Workable, Oracle HCM,
   etc.), but sometimes another job board entirely (LinkedIn shows up
   repeatedly). See _classify_apply_type() for how that distinction is
   made.

5. The `country` field inside the JSON is the only reliable way to keep
   India-only listings — the URL slug pattern the site otherwise uses
   (`{company}-is-hiring-for-{title}-...-india-{date}`) is inconsistent;
   plenty of genuine India postings omit the "-india-" suffix entirely,
   and non-India postings can look just as generic. Non-India records are
   dropped in parse(), before normalize() ever sees them.

6. Description sections are completely free-form per employer (h3 headers
   seen: "General Summary", "Who We Are", "Role Summary", "About Adobe",
   as well as "Key Responsibilities"/"Requirements" on some listings but
   not most). Rather than hunting for two specific header strings and
   silently losing content on every listing that titles them differently,
   we take the entire resolved description HTML blob as-is (stripped to
   plain text) as description_original.

7. This source is windowed to recent postings, not the whole sitemap: only
   jobs posted within the last `max_job_age_hours` (default 24) are kept.
   The sitemap's URL order was verified newest-first by spot-checking real
   postedAt values across the full 1,770-URL range, so fetch() walks it in
   order and stops the first time it sees a posting older than the
   window — every run costs roughly "how many jobs came in since last
   time", not a fixed page count. See fetch()/parse() docstrings for the
   two-layer enforcement (an early-stop optimization in fetch(), plus the
   authoritative recheck in parse() in case that ordering assumption ever
   doesn't hold for some stretch of the sitemap).

apply_type here is classified from the RAW applyUrl only (pre-resolution),
because a scraper's normalize() never sees the pipeline's post-resolution
`resolved_domain`. Every sampled Jobfound applyUrl was already the final,
un-wrapped destination, so this alone was sufficient in practice — but in
case a redirect chain (see pipeline/resolver.py) ever lands on a known
aggregator domain that wasn't visible in the raw URL, pipeline/filter.py
now runs a second, post-resolution pass
(`revalidate_after_resolution`) that re-checks `resolved_domain` against
the same aggregator list and downgrades `is_external` accordingly. The
aggregator domain list itself lives in pipeline/filter.py
(`KNOWN_AGGREGATOR_DOMAINS` / `is_aggregator_domain`), not here, so the
pre- and post-resolution checks can never disagree.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import datetime, timedelta, timezone

import httpx
from selectolax.parser import HTMLParser
from yarl import URL

from config import settings
from pipeline.filter import is_aggregator_domain
from pipeline.salary_parser import parse_salary
from scrapers.base import BaseSource

SITEMAP_URL = "https://www.jobfound.org/sitemap.xml"

# How recent a posting has to be to keep. This, not a fixed page count, is
# what actually bounds a run: fetch() walks the sitemap in order and stops
# once it reaches a posting older than this, so every run pulls "whatever
# is new since last time" rather than a fixed-size slice.
DEFAULT_MAX_JOB_AGE_HOURS = 24

# Circuit breaker only — NOT the intended way to bound a run (that's
# max_job_age_hours above). Sitemap URLs were verified newest-first
# (spot-checked positions 1..1770 against their real postedAt timestamps),
# so fetch() should hit a >24h-old posting and stop long before this. This
# cap just prevents a runaway fetch of the entire ~1,770-URL sitemap in the
# one scenario where the recency signal can't be trusted: postedAt is
# missing/unparseable on every page in a row (fetch() can't tell "stale"
# from "unknown" and keeps going rather than guessing).
DEFAULT_SAFETY_MAX_PAGES = 500

_EMPLOYMENT_TYPE_MAP = {
    "full-time": "full-time",
    "part-time": "part-time",
    "contract": "contract",
    "internship": "internship",
    "temporary": "contract",
}

# React Flight text-chunk push, e.g.: self.__next_f.push([1,"21:T9bf,<h3>..."])
_FLIGHT_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
# initialJob is always immediately followed by ,"similarJobs" in the payload.
_INITIAL_JOB_RE = re.compile(r'"initialJob":(\{.*?\}),"similarJobs"', re.DOTALL)


class JobfoundSource(BaseSource):
    """Scraper for jobfound.org, discovered via its sitemap rather than the
    (client-rendered, robots.txt-disallowed) listing page. See module
    docstring for the full rationale.
    """

    source_name = "jobfound"
    # robots.txt specifies `Crawl-delay: 1` for the paths we use
    # (sitemap.xml + /job/*); 60 rpm / 1s matches that exactly.
    requests_per_minute = 60
    crawl_delay_seconds = 1.0

    def __init__(
        self,
        max_job_age_hours: float = DEFAULT_MAX_JOB_AGE_HOURS,
        safety_max_pages: int = DEFAULT_SAFETY_MAX_PAGES,
    ) -> None:
        super().__init__()
        self.max_job_age_hours = max_job_age_hours
        self.safety_max_pages = safety_max_pages

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------
    async def fetch(self) -> list[dict]:
        """Fetch the sitemap, then walk its /job/{slug} URLs **in order**
        (newest-first, verified directly against real postedAt values),
        fetching each detail page and peeking at its postedAt to decide
        whether to keep going.

        Stops as soon as a posting older than max_job_age_hours is seen —
        that's the real stopping condition every run uses, not a fixed
        count, so each run naturally pulls "whatever's new" and nothing
        more. A page whose postedAt can't be determined doesn't stop the
        walk (we can't conclude it's stale), it's just included and left
        for a downstream stage to decide about; safety_max_pages is the
        only hard ceiling, for the case that signal is unreliable across
        many pages in a row.

        Returns a list of {"url", "html"} dicts; pages that fail to load
        are skipped rather than aborting the run.
        """
        headers = {"User-Agent": random.choice(settings.user_agents)}
        pages: list[dict] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_job_age_hours)

        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers=headers,
            follow_redirects=True,
        ) as client:
            sitemap_response = await client.get(SITEMAP_URL)
            sitemap_response.raise_for_status()
            job_urls = _extract_sitemap_job_urls(sitemap_response.text)

            for url in job_urls[: self.safety_max_pages]:
                try:
                    response = await client.get(url)
                except (httpx.TimeoutException, httpx.RequestError):
                    # One unreachable detail page shouldn't sink the run —
                    # skip it and keep walking.
                    await asyncio.sleep(self.crawl_delay_seconds)
                    continue

                if response.status_code == 200:
                    html = response.text
                    # Reuse the real extraction path for the peek (rather
                    # than a separate lightweight parser) so there's only
                    # ever one place that knows how to read postedAt out
                    # of a page — parse() re-extracts the same page in
                    # full afterward; the double work is cheap compared to
                    # the network round-trip that dominates each iteration.
                    peeked = _extract_initial_job(html)
                    posted_at = _parse_iso_datetime(peeked.get("postedAt")) if peeked else None
                    if posted_at is not None and posted_at < cutoff:
                        # Sitemap is newest-first: once we hit one posting
                        # older than the cutoff, everything after it is
                        # expected to be older too.
                        break
                    pages.append({"url": url, "html": html})

                await asyncio.sleep(self.crawl_delay_seconds)

        return pages

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------
    def parse(self, raw: list[dict]) -> list[dict]:
        """Extract the embedded `initialJob` payload (+ resolved
        description text) from each detail page's HTML, keeping only
        India listings posted within max_job_age_hours. One raw record
        per surviving job posting.

        This recency check is the authoritative one (fetch()'s early-stop
        is just an optimization to avoid fetching pages we already know
        we won't want) — enforced again here in case fetch()'s
        newest-first assumption ever doesn't hold for some stretch of the
        sitemap. A posting with no usable postedAt is dropped too: the
        point of this source is "recent India postings", and we can't
        confirm recency for one we can't date.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_job_age_hours)
        records: list[dict] = []
        for page in raw:
            job = _extract_initial_job(page["html"])
            if job is None:
                continue
            country = (job.get("country") or "").strip().lower()
            if country != "india":
                # Jobfound covers multiple countries; this is an India
                # source, so anything else (including unknown/blank
                # country) is out of scope here.
                continue
            posted_at = _parse_iso_datetime(job.get("postedAt"))
            if posted_at is None or posted_at < cutoff:
                continue
            job["_source_url"] = page["url"]
            records.append(job)
        return records

    # ------------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------------
    def normalize(self, raw_record: dict) -> dict:
        missing: list[str] = []

        title = raw_record.get("title") or ""
        company = raw_record.get("companyName") or ""
        slug = raw_record.get("slug") or ""
        if not slug:
            missing.append("external_id")

        location = raw_record.get("location") or None
        if not location:
            missing.append("location")

        workplace_type = (raw_record.get("workplaceType") or "").strip().lower()
        if workplace_type:
            is_remote = workplace_type == "remote"
        else:
            is_remote = False
            missing.append("is_remote")

        job_type_raw = raw_record.get("jobType")
        if job_type_raw:
            employment_type = _EMPLOYMENT_TYPE_MAP.get(
                job_type_raw.strip().lower(), job_type_raw.strip().lower()
            )
        else:
            employment_type = None
            missing.append("employment_type")

        experience_raw = raw_record.get("experience")
        seniority = _infer_seniority(experience_raw)
        if seniority is None:
            missing.append("seniority")

        salary_raw = raw_record.get("salary") or None
        parsed_salary = parse_salary(salary_raw)
        if not parsed_salary.has_salary:
            missing.append("salary_min")
            missing.append("salary_max")
            missing.append("salary_period")
            if not salary_raw:
                missing.append("salary_raw")

        description_html = raw_record.get("_description_html")
        description_original = _html_to_text(description_html) if description_html else None
        description_available = bool(description_original)
        if not description_available:
            missing.append("description_original")

        skills_raw = raw_record.get("skills") or ""
        tags = [s.strip() for s in skills_raw.split(",") if s.strip()]
        role_category = raw_record.get("domain")
        if role_category and role_category not in tags:
            tags.append(role_category)
        if not tags:
            missing.append("tags")

        apply_url = raw_record.get("applyUrl") or ""
        if not apply_url:
            missing.append("raw_apply_url")
        apply_type = _classify_apply_type(apply_url)

        posted_at = _parse_iso_datetime(raw_record.get("postedAt"))
        if posted_at is None:
            missing.append("posted_at")

        return {
            "external_id": slug,
            "title": title,
            "company": company,
            "location": location,
            "is_remote": is_remote,
            "employment_type": employment_type,
            "seniority": seniority,
            "salary_min": parsed_salary.salary_min,
            "salary_max": parsed_salary.salary_max,
            "salary_currency": "INR",
            "salary_period": parsed_salary.salary_period,
            "salary_raw": salary_raw,
            "has_salary": parsed_salary.has_salary,
            "description_original": description_original,
            "description_available": description_available,
            "tags": tags,
            "apply_type": apply_type,
            "raw_apply_url": apply_url,
            "posted_at": posted_at,
            "source_fields_missing": missing,
        }


# ==========================================================================
# Sitemap parsing
# ==========================================================================
def _extract_sitemap_job_urls(sitemap_xml: str) -> list[str]:
    """Pull every /job/{slug} <loc> entry out of the sitemap, in document
    order (the sitemap does not indicate country, so this is unfiltered —
    parse() drops non-India records after fetching each page).

    The host is matched with `www.` optional, deliberately: as of
    2026-08-14 the site canonicalized onto the bare apex domain and every
    <loc> is now `https://jobfound.org/job/...`. Requiring `www.` here
    silently matched zero of 2,216 job URLs, which fetch() could not tell
    apart from "the sitemap has nothing recent" — the whole source
    reported fetched=0 while listings were live on the site.
    """
    return re.findall(
        r"<loc>(https://(?:www\.)?jobfound\.org/job/[^<]+)</loc>", sitemap_xml
    )


# ==========================================================================
# React Flight ("RSC") payload parsing
# ==========================================================================
def _flight_buffer(html: str) -> str:
    """Reassemble the full Next.js Flight text stream from a detail page's
    HTML.

    The stream is delivered as many `self.__next_f.push([1,"..."])` calls;
    a single logical row can be split across multiple push calls at
    arbitrary byte offsets (observed directly: a webpack chunk-list string
    was split mid-token across three consecutive pushes). Each push's
    string literal must be JSON-unescaped individually (it's a JS string
    literal — `json.loads('"' + chunk + '"')` handles \\", \\n, \\uXXXX
    etc. correctly, unlike a raw unicode-escape decode), then all pushes
    concatenated **with no separator** — the newlines that actually
    delimit rows are literal characters already inside the decoded
    content, not something introduced by push boundaries.
    """
    parts = []
    for raw_chunk in _FLIGHT_PUSH_RE.findall(html):
        try:
            parts.append(json.loads('"' + raw_chunk + '"'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return "".join(parts)


def _extract_initial_job(html: str) -> dict | None:
    """Extract the `initialJob` object and resolve its description text
    reference from one detail page's HTML. Returns None if the page
    doesn't contain a parseable job payload (e.g. a 404 or non-job page).
    """
    buffer = _flight_buffer(html)

    match = _INITIAL_JOB_RE.search(buffer)
    if not match:
        return None

    try:
        job = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    description_ref = job.get("description")
    if isinstance(description_ref, str) and description_ref.startswith("$"):
        # Streamed separately — resolve the Flight text-row reference.
        job["_description_html"] = _resolve_flight_text_row(buffer, description_ref[1:])
    elif isinstance(description_ref, str) and description_ref:
        # Some listings inline the HTML directly in initialJob instead of
        # streaming it as a separate row (observed directly: e.g. Algoleap
        # Technologies' posting has literal "<h3>...</h3>..." here, not a
        # "$21"-style reference) — use it as-is.
        job["_description_html"] = description_ref
    else:
        job["_description_html"] = None

    return job


def _resolve_flight_text_row(buffer: str, row_id: str) -> str | None:
    """Resolve a Flight text-row reference (e.g. row_id "21" for a
    `"description":"$21"` reference) to its actual text content.

    Text rows have the form `<id>:T<hex-byte-length>,<content>`. Verified
    directly against live pages: consecutive rows are NOT reliably
    newline-separated (a row can butt directly against the previous one's
    last byte with zero delimiter — e.g. `..."industry":"Software
    Engineering"}21:T9bf,<h3>General Summary...` was observed with no `\n`
    anywhere near the boundary). The only thing that reliably delimits a
    row's content is its own declared byte length, so that's what we use:
    locate the `<id>:T<hexlen>,` header, then slice out exactly `hexlen`
    UTF-8 bytes starting right after the comma.

    The lookbehind guards against `row_id` matching as a substring of a
    longer id (e.g. searching for id "1" inside "21:T...").
    """
    pattern = re.compile(rf"(?<![0-9a-zA-Z]){re.escape(row_id)}:T([0-9a-fA-F]+),")
    match = pattern.search(buffer)
    if not match:
        return None

    byte_length = int(match.group(1), 16)
    buffer_bytes = buffer.encode("utf-8")
    content_start = len(buffer[: match.end()].encode("utf-8"))
    content_bytes = buffer_bytes[content_start : content_start + byte_length]
    return content_bytes.decode("utf-8", errors="replace")


# ==========================================================================
# Field normalization helpers
# ==========================================================================
def _html_to_text(description_html: str) -> str | None:
    """Strip the description HTML down to readable plain text."""
    text = HTMLParser(description_html).text(separator="\n", strip=True)
    return text or None


def _infer_seniority(experience_raw: str | None) -> str | None:
    """Infer a canonical seniority bucket from Jobfound's free-form
    `experience` field (observed values: "0", "2", "2-4", "5+", ...).

    This is a heuristic, not an authoritative signal — seniority itself
    is inherently approximate per the canonical schema. We take the
    lower bound of any range/plus-suffixed value as "years of experience
    required" and bucket from there.
    """
    if not experience_raw:
        return None

    match = re.search(r"\d+", experience_raw)
    if not match:
        return None
    years = int(match.group())

    if years == 0:
        return "fresher"
    if years <= 2:
        return "junior"
    if years <= 5:
        return "mid"
    if years <= 8:
        return "senior"
    return "lead"


def _classify_apply_type(apply_url: str) -> str:
    """Classify an applyUrl as EXTERNAL / DIRECT / UNKNOWN from the raw
    URL alone (no network access here — the pipeline resolves the URL
    later, and re-checks the *resolved* domain against the same
    aggregator list via pipeline/filter.py::revalidate_after_resolution —
    see that module's docstring for why this needs a second pass there
    too). Errs toward UNKNOWN whenever the destination isn't clearly a
    company's own page, per this source's stated policy.
    """
    if not apply_url:
        return "UNKNOWN"

    domain = URL(apply_url).host
    if not domain:
        return "UNKNOWN"

    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[len("www."):]

    if domain == "jobfound.org" or domain.endswith(".jobfound.org"):
        return "DIRECT"

    if is_aggregator_domain(domain):
        # Looks like another job board, not the hiring company's own page.
        # is_aggregator_domain is the same pipeline-level list used for
        # the post-resolution recheck, so pre- and post-resolution
        # classification can never disagree about what counts as an
        # aggregator.
        return "UNKNOWN"

    return "EXTERNAL"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse Jobfound's ISO 8601 postedAt timestamp (e.g.
    "2026-08-07T11:20:49.459Z") into an aware datetime. Never raises.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
