"""
Talentd (talentd.in) source.

Findings from direct, live, read-only inspection of talentd.in (robots.txt,
`/jobs/sitemap.xml`, the `/jobs` listing page, and real `/jobs/{slug}` detail
pages) that shape everything below:

1. `https://www.talentd.in/robots.txt` disallows `/api/` for generic user
   agents (so this source never touches it) and disallows several
   multi-filter `/jobs?...` query combos (`?sort=`, `?batch=`, and 2-3-way
   combinations of `employment_type`/`role_category`/`city`/`job_type`).
   Plain `/jobs?page=N` and every `/jobs/{slug}` detail page are `Allow`ed.
   No `Crawl-delay` is published. It declares
   `Sitemap: https://www.talentd.in/jobs/sitemap.xml` (a separate, more
   specific sitemap than the site-wide `/sitemap.xml`).

2. That sitemap is a flat (non-index) list of ~4,027 `<url>` entries, each
   with a `<lastmod>`. Individual job-posting entries are verified sorted
   newest-first by lastmod (spot-checked positions 30-45, 500-505, and
   2000-2005 — strictly decreasing). The first ~13 entries are category/city
   hub pages (`/jobs/it-software-jobs`, `/jobs/jobs-in-bangalore`, etc.)
   whose `<lastmod>` is always "now" (they're dynamically generated, not
   dated content) — these sort first regardless of the newest-first rule
   below them, but that's harmless: parse() drops them structurally (see
   point 4) rather than needing a hardcoded skip-count. This lets fetch()
   reuse the same "walk in order, stop once lastmod is older than the
   cutoff" strategy as the jobfound source, instead of crawling the
   400-page paginated `/jobs?page=N` listing.

3. `/jobs/{slug}` detail pages are Next.js App Router, server-rendered via
   React Server Components ("Flight") streaming
   (`self.__next_f.push([1,"..."])`), the same general delivery mechanism
   jobfound.org uses. A schema.org `JobPosting` JSON-LD object is embedded
   in that stream — but, verified directly against a real captured page,
   it is delivered as its **own single, self-contained push chunk** (the
   chunk's entire decoded content is exactly one JSON document:
   `{"@context":...,"@graph":[{"@type":"JobPosting",...}, {"@type":
   "BreadcrumbList",...}]}`), not interleaved with other rows the way
   jobfound's `initialJob`/description text rows are. That means, unlike
   jobfound, no byte-length-prefixed row resolution or buffer
   concatenation is needed here: decode each push individually (one level
   of JS string unescaping, same `json.loads('"' + chunk + '"')` trick),
   and `json.loads()` the decoded string directly the moment it contains
   the JobPosting anchor. Do not assume this requires a second escaping
   layer "just in case" — that was disproven by direct inspection.

4. The JSON-LD's own `description` field is a **truncated SEO snippet**
   ("...&hellip;"-terminated), not the full job description. The full
   description is separate, literal (non-streamed) server-rendered HTML
   in a `<div class="jobContent_jobContent__{buildhash}">...</div>` block
   elsewhere in the same page (verified: `jobContent_jobContent__baQN3` on
   one real page). The hash suffix is a CSS-module build artifact and
   should not be assumed stable across deploys — match on the
   `jobContent_jobContent__` prefix, not the full class name.

5. The real "Apply" destination is **not** the JSON-LD's `url` field
   (that's talentd.in's own canonical page URL for the posting) — it's a
   plain, unescaped `<a href="..." target="_blank"
   rel="noopener noreferrer">Apply Now</a>` elsewhere in the literal DOM,
   pointing straight at the hiring company's own ATS (verified: a Workday
   URL on the sampled Genpact posting). Using the JSON-LD `url` here would
   silently classify every listing as DIRECT instead of EXTERNAL — this is
   the single most important correctness point in this file.

6. Pages with no `JobPosting` JSON-LD (the ~13 sitemap hub pages, and any
   other non-posting URL that might end up in this sitemap) are dropped in
   parse() simply because the extractor finds nothing — no separate
   position-based or URL-pattern-based skip logic is needed.

7. `jobLocation[0].address.addressCountry` was "IN" on every sample
   checked, and the site's whole navigation/category structure is
   India-city-based, so talentd.in appears to be India-specific by
   construction. parse() still defensively drops anything where that field
   is present and NOT "IN" (in case a stray non-India posting ever shows
   up) but does not drop a listing just because the field is absent
   entirely — absence isn't evidence of being non-Indian on this source.

8. talentd.in has no structured remote-work field at all (unlike jobfound's
   `workplaceType`) — `is_remote` here is always an inferred guess from
   title/location/slug text, never sourced data, so it's always recorded
   in `source_fields_missing` regardless of which way the heuristic lands.

9. This is a software/IT-specific aggregator by product decision, not
   talentd.in's own scope — the site itself covers many other categories,
   visible directly in its own `/jobs/sitemap.xml` hub-page entries:
   `it-software-jobs`, `core-engineering-jobs`, `banking-finance-jobs`,
   `bpo-customer-support-jobs`, `sales-marketing-jobs`, `hr-admin-jobs`,
   `design-jobs`, `healthcare-pharma-jobs`, `manufacturing-operations-jobs`,
   `research-science-jobs`, `government-defence-jobs`, `other-jobs`. No
   per-job JSON-LD field carries that category, though (confirmed: the
   JobPosting object has no `industry`/`occupationalCategory`/department
   field), so parse() infers scope from `title` + `skills` text against
   that same vocabulary: `_ROLE_EXCLUDE_RE` drops anything that reads as
   BPO/customer support, sales/marketing, or HR/admin even if it also
   contains a software-ish word (e.g. "Software Sales Executive" is a
   sales role, not an engineering one); `_ROLE_INCLUDE_RE` then requires a
   software/IT development signal to keep anything at all, so a generic,
   signal-free title (e.g. a "Trainee"/"Associate" posting with no tech
   keywords) is dropped too, not just the three explicitly-named
   categories. Both lists are necessarily heuristic, not exhaustive — see
   `_is_software_related()`.

apply_type here is classified from the DOM apply link only (pre-resolution,
same policy as jobfound) via _classify_apply_type(), which reuses
pipeline.filter.is_aggregator_domain — the same aggregator list the
pipeline's post-resolution revalidate_after_resolution() pass uses, so the
two checks can never disagree. See pipeline/filter.py's module docstring
for why that second, post-resolution pass exists at all.
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

SITEMAP_URL = "https://www.talentd.in/jobs/sitemap.xml"

# How recent a posting has to be to keep. Same role as jobfound's constant of
# the same name: this, not a fixed page count, is what actually bounds a run.
DEFAULT_MAX_JOB_AGE_HOURS = 24

# Circuit breaker only, not the intended stopping condition (see point 2 in
# the module docstring). Sized well under the sitemap's ~4,027 total entries
# since a 24h-old cutoff should be reached after at most a few hundred
# newest-first entries in normal operation.
DEFAULT_SAFETY_MAX_PAGES = 400

# schema.org employmentType values, normalized (lowercase, spaces/underscores
# collapsed to hyphens) before lookup. Only "full-time" has been observed on
# a real listing so far — the rest are best-effort guesses at the likely
# schema.org-style values talentd would emit for internship/part-time/
# contract postings (the site does have `/jobs/internships` etc. category
# pages, so those employment types certainly exist somewhere in its data;
# their exact raw string just hasn't been sampled directly yet). Treat this
# table as provisional and revisit once real internship/part-time/contract
# postings have been spot-checked.
_EMPLOYMENT_TYPE_MAP = {
    "full-time": "full-time",
    "part-time": "part-time",
    "contract": "contract",
    "contractor": "contract",
    "temporary": "contract",
    "internship": "internship",
    "intern": "internship",
}

# schema.org baseSalary.value.unitText -> the phrase parse_salary() expects.
_SALARY_UNIT_PHRASE = {
    "YEAR": "per annum",
    "MONTH": "per month",
    "HOUR": "per hour",
}

# Role-scope filter — this aggregator is software/IT-specific; talentd.in
# itself is not (see module docstring point 9). No structured category
# field exists per-job, so scope is inferred from title + skills text.
# Checked first: any match here drops the listing outright, even if it
# also matches _ROLE_INCLUDE_RE (e.g. "Software Sales Executive" is a
# sales role, not a software-engineering one).
_ROLE_EXCLUDE_RE = re.compile(
    r"\b("
    r"bpo|customer support|customer service|voice process|non-voice|non voice"
    r"|telecaller|telecalling|call center|call centre|chat support|back office"
    r"|sales executive|sales manager|sales associate|sales officer"
    r"|business development|bde|field sales|telesales"
    r"|marketing executive|marketing manager|digital marketing|brand marketing"
    r"|content marketing"
    r"|hr executive|hr manager|hr generalist|human resource|recruiter|recruitment"
    r"|talent acquisition|admin executive|administrative|office admin"
    r"|front office|receptionist"
    r")\b",
    re.IGNORECASE,
)

# Checked second, only if _ROLE_EXCLUDE_RE didn't match: at least one of
# these must be present (in title or skills) for a listing to be kept at
# all — a generic, signal-free title/skills combo is dropped too, not just
# the explicitly-excluded categories above.
_ROLE_INCLUDE_RE = re.compile(
    r"\b("
    r"software|developer|programmer|sde|full stack|fullstack"
    r"|front-?end|back-?end|devops"
    r"|data engineer|data scientist|data analyst"
    r"|machine learning|ml engineer|ai engineer"
    r"|qa engineer|sdet|test engineer|automation engineer"
    r"|cloud engineer|site reliability|sre"
    r"|mobile developer|android developer|ios developer|web developer"
    r"|cybersecurity|security engineer"
    r"|database administrator|dba|network engineer|systems engineer"
    r")\b",
    re.IGNORECASE,
)


def _is_software_related(title: str, skills: str) -> bool:
    """Scope check: keep only software/IT-specific listings (see module
    docstring point 9). Excludes take priority over includes.
    """
    text = f"{title} {skills}"
    if _ROLE_EXCLUDE_RE.search(text):
        return False
    return bool(_ROLE_INCLUDE_RE.search(text))

# React Flight text-chunk push, e.g.: self.__next_f.push([1,"{\"@context\":..."])
# Identical mechanism to jobfound's — this is generic Next.js RSC streaming,
# not site-specific.
_FLIGHT_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')

# <url><loc>...</loc><lastmod>...</lastmod> pairs, captured together so
# ordering can never desync between two independent findall() calls.
_SITEMAP_ENTRY_RE = re.compile(
    r"<loc>(https://www\.talentd\.in/jobs/[^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>"
)

_LD_JSON_SCRIPT_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)

# Anchor used to cheaply skip decoded push chunks that obviously aren't the
# JobPosting block, before paying for a full json.loads(). Whitespace-
# tolerant (\s*) rather than a plain substring check, since the real site's
# JSON is minified with no spaces but nothing guarantees that stays true.
_JOB_POSTING_ANCHOR_RE = re.compile(r'"@type"\s*:\s*"JobPosting"')


class TalentdSource(BaseSource):
    """Scraper for talentd.in, discovered via its dedicated jobs sitemap
    rather than the 400-page paginated listing. See module docstring for
    the full rationale.
    """

    source_name = "talentd"
    # robots.txt publishes no Crawl-delay for this site (unlike jobfound.org's
    # explicit `Crawl-delay: 1`) and it sits behind Cloudflare with edge
    # caching tuned for infrequent origin hits (Cache-Control: max-age=300,
    # s-maxage=3600) — erring more conservative than jobfound's 60rpm/1.0s
    # pending real-run evidence it's safe to tighten.
    requests_per_minute = 30
    crawl_delay_seconds = 1.5

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
        """Fetch the jobs sitemap, then walk its (url, lastmod) pairs **in
        order** (newest-first, verified directly against the real sitemap),
        fetching each detail page and stopping once lastmod is older than
        max_job_age_hours.

        This lastmod-based stop is an optimization only — cheaper than
        jobfound's approach of peeking at each fetched page's own posted
        date, since the sitemap already publishes a per-URL timestamp. It
        is NOT the authoritative recency check: parse() independently
        re-derives recency from each page's real `datePosted`, in case
        lastmod (a page-modification time) ever diverges from the actual
        posting date, or the newest-first ordering assumption doesn't hold
        for some stretch of the sitemap.

        Never constructs any `/jobs?...` query URL — only sitemap.xml and
        bare `/jobs/{slug}` detail pages are ever touched, so robots.txt
        compliance holds by construction, without needing to special-case
        the disallowed filter-combo query strings.

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
            entries = _extract_sitemap_entries(sitemap_response.text)

            for url, lastmod_raw in entries[: self.safety_max_pages]:
                lastmod = _parse_iso_datetime(lastmod_raw)
                if lastmod is not None and lastmod < cutoff:
                    # Sitemap is newest-first for actual postings; once we
                    # hit an entry older than the cutoff, everything after
                    # it is expected to be older too. (Hub pages sort first
                    # regardless, with an always-fresh lastmod — they never
                    # trigger this break; parse() drops them instead.)
                    break

                try:
                    response = await client.get(url)
                except (httpx.TimeoutException, httpx.RequestError):
                    # One unreachable detail page shouldn't sink the run.
                    await asyncio.sleep(self.crawl_delay_seconds)
                    continue

                if response.status_code == 200:
                    pages.append({"url": url, "html": response.text})

                await asyncio.sleep(self.crawl_delay_seconds)

        return pages

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------
    def parse(self, raw: list[dict]) -> list[dict]:
        """Extract the JobPosting JSON-LD (+ DOM apply link + description
        HTML) from each detail page, keeping only software/IT-specific
        India listings posted within max_job_age_hours.

        The recency check here is authoritative (fetch()'s lastmod-based
        stop is only an optimization — see fetch()'s docstring). A posting
        with no usable datePosted is dropped: recency can't be confirmed
        for something that can't be dated.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_job_age_hours)
        records: list[dict] = []
        for page in raw:
            job_ld = _extract_job_posting_ld(page["html"])
            if job_ld is None:
                # Not a job-posting page (sitemap hub page, 404, etc.) —
                # structurally unparseable as a listing, drop it here.
                continue

            if not _is_software_related(job_ld.get("title") or "", job_ld.get("skills") or ""):
                # Out of scope for this aggregator — BPO/customer support,
                # sales/marketing, HR/admin, or just no software/IT signal
                # at all. See module docstring point 9.
                continue

            country = _country_code(job_ld)
            if country is not None and country != "IN":
                continue

            posted_at = _parse_iso_datetime(job_ld.get("datePosted"))
            if posted_at is None or posted_at < cutoff:
                continue

            job_ld["_source_url"] = page["url"]
            job_ld["_slug"] = page["url"].rstrip("/").rsplit("/", 1)[-1]
            job_ld["_apply_url"] = _extract_apply_url(page["html"])
            job_ld["_description_html"] = _extract_description_html(page["html"])
            records.append(job_ld)
        return records

    # ------------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------------
    def normalize(self, raw_record: dict) -> dict:
        missing: list[str] = []

        title = raw_record.get("title") or ""
        company = (raw_record.get("hiringOrganization") or {}).get("name") or ""

        slug = raw_record.get("_slug") or ""
        if not slug:
            missing.append("external_id")

        location = _format_location(raw_record.get("jobLocation"))
        if not location:
            missing.append("location")

        # schema.org's employmentType is nominally a single enum value, but
        # verified live on a real talentd listing it can carry multiple
        # comma-separated descriptors (e.g. "full-time, remote") — split
        # and map each token independently rather than mapping the whole
        # string as one key (which would produce a garbage compound value
        # like "full-time,-remote"). Non-canonical descriptors such as
        # "remote" (a work-mode, not one of our employment_type values) are
        # simply skipped here — is_remote picks that signal up separately.
        employment_type_raw = raw_record.get("employmentType") or ""
        employment_type = None
        for token in re.split(r"[,/]", employment_type_raw):
            key = re.sub(r"[\s_]+", "-", token.strip().lower())
            mapped = _EMPLOYMENT_TYPE_MAP.get(key)
            if mapped:
                employment_type = mapped
                break
        if employment_type is None:
            missing.append("employment_type")

        # No structured remote-work field exists on this source — the
        # result is always an inferred guess, never sourced data, so it's
        # always flagged missing regardless of which branch fires. Folds in
        # employmentType's raw text too, since "remote" has been observed
        # as one of its comma-separated tokens on a real listing.
        is_remote = _infer_is_remote(title, location, slug, employment_type_raw)
        missing.append("is_remote")

        seniority = _infer_seniority(raw_record.get("experienceRequirements"), title)
        if seniority is None:
            missing.append("seniority")

        salary_raw = _build_salary_raw(raw_record.get("baseSalary"))
        parsed_salary = parse_salary(salary_raw)
        if not parsed_salary.has_salary:
            missing.append("salary_min")
            missing.append("salary_max")
            missing.append("salary_period")
            if not salary_raw:
                missing.append("salary_raw")

        description_html = raw_record.get("_description_html")
        description_original = _html_to_text(description_html) if description_html else None
        if not description_original:
            # Fall back to the JSON-LD's own (truncated) description rather
            # than storing nothing — lower quality, but non-empty beats
            # empty, and description_available still reflects that it's a
            # degraded source.
            fallback = raw_record.get("description")
            description_original = _html_to_text(fallback) if fallback else None
        description_available = bool(description_original)
        if not description_available:
            missing.append("description_original")

        skills_raw = raw_record.get("skills") or ""
        tags = [s.strip() for s in skills_raw.split(",") if s.strip()]
        if not tags:
            missing.append("tags")

        apply_url = raw_record.get("_apply_url") or ""
        if not apply_url:
            missing.append("raw_apply_url")
        apply_type = _classify_apply_type(apply_url)

        posted_at = _parse_iso_datetime(raw_record.get("datePosted"))
        if posted_at is None:
            missing.append("posted_at")

        currency = (raw_record.get("baseSalary") or {}).get("currency") or "INR"

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
            "salary_currency": currency,
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
def _extract_sitemap_entries(sitemap_xml: str) -> list[tuple[str, str]]:
    """Pull every (loc, lastmod) pair for a /jobs/{slug} URL out of the
    sitemap, in document order. This includes the ~13 category/hub pages
    (harmless — parse() drops them once it finds no JobPosting JSON-LD).
    """
    return _SITEMAP_ENTRY_RE.findall(sitemap_xml)


# ==========================================================================
# React Flight ("RSC") payload parsing
# ==========================================================================
def _extract_job_posting_ld(html: str) -> dict | None:
    """Extract the schema.org JobPosting JSON-LD object from one detail
    page's HTML. Returns None if no JobPosting block is found (e.g. a
    sitemap hub page, a 404, or any other non-posting page).

    Tries a literal `<script type="application/ld+json">` tag first (cheap,
    and future-proofs against talentd ever switching to literal-tag
    rendering). Falls back to the RSC stream, where — verified directly
    against a real page — the JobPosting JSON-LD is delivered as its own
    single, self-contained push chunk: decoding one push (one level of JS
    string unescaping) yields a complete, directly-parseable JSON document,
    with no separate row-resolution or buffer-concatenation step needed
    (unlike jobfound's initialJob/description handling).
    """
    for raw in _LD_JSON_SCRIPT_RE.findall(html):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = _find_job_posting(obj)
        if found is not None:
            return found

    for raw_chunk in _FLIGHT_PUSH_RE.findall(html):
        try:
            decoded = json.loads('"' + raw_chunk + '"')
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not _JOB_POSTING_ANCHOR_RE.search(decoded):
            continue
        try:
            obj = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        found = _find_job_posting(obj)
        if found is not None:
            return found

    return None


def _find_job_posting(obj) -> dict | None:
    """Locate a JobPosting object either at the top level or inside an
    `@graph` list (talentd nests it in @graph alongside a BreadcrumbList).
    """
    if isinstance(obj, dict):
        if obj.get("@type") == "JobPosting":
            return obj
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
    return None


# ==========================================================================
# DOM extraction (apply link + full description — both live outside the
# JSON-LD, as literal server-rendered HTML)
# ==========================================================================
def _extract_apply_url(html: str) -> str | None:
    """Extract the real "Apply Now" destination from the DOM. This is
    deliberately NOT the JSON-LD's `url` field — see module docstring
    point 5. Prefers a target="_blank" anchor whose visible text mentions
    "apply"; falls back to the first target="_blank" anchor that isn't a
    talentd.in-hosted link, in case wording ever changes.
    """
    tree = HTMLParser(html)
    blank_links = tree.css('a[target="_blank"]')

    for node in blank_links:
        href = node.attributes.get("href")
        if href and "apply" in node.text(strip=True).lower():
            return href

    for node in blank_links:
        href = node.attributes.get("href")
        if not href:
            continue
        host = URL(href).host or ""
        if host and "talentd.in" not in host.lower():
            return href

    return None


def _extract_description_html(html: str) -> str | None:
    """Extract the full job-description HTML from the
    `jobContent_jobContent__{buildhash}` div. Matches on the class-name
    prefix, not the exact (build-hash-suffixed) class — see module
    docstring point 4.
    """
    tree = HTMLParser(html)
    for node in tree.css("div"):
        class_attr = node.attributes.get("class") or ""
        if "jobContent_jobContent__" in class_attr:
            return node.html
    return None


# ==========================================================================
# Field normalization helpers
# ==========================================================================
def _html_to_text(html_fragment: str) -> str | None:
    """Strip an HTML fragment down to readable plain text."""
    text = HTMLParser(html_fragment).text(separator="\n", strip=True)
    return text or None


def _country_code(job_ld: dict) -> str | None:
    """Pull addressCountry out of the first jobLocation entry, uppercased.
    Returns None if there's no jobLocation/address/addressCountry at all
    (absence, not evidence of being non-Indian — see module docstring
    point 7).
    """
    locations = job_ld.get("jobLocation")
    if not isinstance(locations, list) or not locations:
        return None
    address = (locations[0] or {}).get("address") or {}
    country = address.get("addressCountry")
    return country.strip().upper() if country else None


def _format_location(job_locations) -> str | None:
    """Build a "City, State" string from jobLocation[0].address. Returns
    None if neither locality nor region is present.
    """
    if not isinstance(job_locations, list) or not job_locations:
        return None
    address = (job_locations[0] or {}).get("address") or {}
    locality = (address.get("addressLocality") or "").strip()
    region = (address.get("addressRegion") or "").strip()
    if locality and region:
        return f"{locality}, {region}"
    return locality or region or None


def _infer_is_remote(title: str, location: str | None, slug: str, *extra_text: str) -> bool:
    """Heuristic only — talentd has no structured remote-work field (see
    module docstring point 8). "hybrid" is explicitly treated as NOT
    remote even if "remote"/"virtual" also appears somewhere in the text.
    """
    combined = " ".join(filter(None, [title, location, slug, *extra_text])).lower()
    if "hybrid" in combined:
        return False
    return "remote" in combined or "virtual" in combined


def _infer_seniority(experience_raw: str | None, title: str) -> str | None:
    """Infer a canonical seniority bucket from talentd's free-form
    `experienceRequirements` field (observed shape: "0-2 years"), with a
    title-keyword fallback for postings that omit experienceRequirements
    entirely. Same bucket thresholds as jobfound's heuristic — seniority
    is inherently approximate per the canonical schema either way.
    """
    if experience_raw:
        match = re.search(r"\d+", experience_raw)
        if match:
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

    if title and "fresher" in title.lower():
        return "fresher"

    return None


def _build_salary_raw(base_salary: dict | None) -> str | None:
    """Turn structured baseSalary.value.{minValue,maxValue,unitText} into a
    human-readable string parse_salary() can consume, reusing the one
    salary-parsing code path in the codebase rather than a second parser
    that duplicates parse_salary()'s number/period logic. Known gap: only
    unitText="YEAR" has been observed live; parse_salary() only recognizes
    annual/monthly/hourly phrasing, so an unsupported unit (e.g. "WEEK")
    would round-trip to "no salary" even though structured data existed.
    """
    if not base_salary:
        return None
    value = base_salary.get("value") or {}
    min_value = value.get("minValue")
    max_value = value.get("maxValue")
    unit_phrase = _SALARY_UNIT_PHRASE.get((value.get("unitText") or "").upper())
    if min_value is None or unit_phrase is None:
        return None
    if max_value is not None and max_value != min_value:
        return f"{min_value}-{max_value} {unit_phrase}"
    return f"{min_value} {unit_phrase}"


def _classify_apply_type(apply_url: str) -> str:
    """Classify an apply URL as EXTERNAL / DIRECT / UNKNOWN from the raw
    URL alone (no network access here — see pipeline/filter.py's module
    docstring for why a second, post-resolution pass also exists). Errs
    toward UNKNOWN whenever the destination isn't clearly a company's own
    page.
    """
    if not apply_url:
        return "UNKNOWN"

    domain = URL(apply_url).host
    if not domain:
        return "UNKNOWN"

    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[len("www."):]

    if domain == "talentd.in" or domain.endswith(".talentd.in"):
        return "DIRECT"

    if is_aggregator_domain(domain):
        return "UNKNOWN"

    return "EXTERNAL"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse talentd's ISO 8601 timestamps (e.g. "2026-08-11T10:26:11.000Z",
    used for both datePosted and sitemap lastmod) into an aware datetime.
    Never raises.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
