"""Build one short post that works, unchanged, on X, WhatsApp and Telegram.

Two decisions shape everything in this module, and neither is cosmetic:

**One message, not three.** X caps a post at 280 characters and counts *every*
URL as 23 characters regardless of its real length. A "5 jobs with 5 apply
links" post costs roughly 68 characters per job, so five of them land near 370
- physically unpostable on X. Listing job *titles* and giving a single link to
our own site fits in ~200 characters instead, which is why the same text can go
to all three platforms verbatim. Formatting syntax also differs per platform
(WhatsApp `*bold*`, Telegram `**bold**`/HTML, X none at all), so the digest is
deliberately **plain text with no markup** - anything else renders as literal
asterisks somewhere.

**The link points at our own site, never at the employer's apply page.** A post
containing the direct Workday/Greenhouse URL sends the reader straight past us:
no pageview, no ad impression, free marketing for the employer. Since ad revenue
is the point of the site, every social link has to land on our own listing page
and let the reader click Apply from there. If you are ever tempted to "help the
user" by inlining apply links here, that is the trade being made.

The site URL comes from `settings.site_base_url` rather than being hardcoded
because the site currently runs on a `.vercel.app` subdomain (no domain budget
yet) and will move to a real domain later - AdSense will not approve a
subdomain someone else owns. One config change has to be enough to switch it.
"""
from __future__ import annotations

from typing import Iterable, Protocol

# X counts every URL as exactly 23 characters after t.co wrapping, however
# long the real URL is. Counting len(url) instead would make a long URL look
# unpostable and silently drop job lines that would in fact have fit.
X_URL_LENGTH = 23
X_CHARACTER_LIMIT = 280

# Titles longer than this are cut so one job can't eat the whole budget and
# starve the others out of the list.
MAX_TITLE_CHARS = 42

_HEADER_SINGULAR = "\U0001f680 1 new tech job in India today"
_HEADER_PLURAL = "\U0001f680 {count} new tech jobs in India today"
_CALL_TO_ACTION = "Apply \U0001f449 {url}"


class _JobLike(Protocol):
    """Anything with a title and a company.

    Duck-typed on purpose so this module stays independent of both
    `db.models.JobModel` and `api.schemas.JobOut` - it formats text and should
    not care which layer handed it the rows.
    """

    title: str
    company: str


def _truncate(text: str, limit: int = MAX_TITLE_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    # Cut at a word boundary where possible so the result reads as a title
    # rather than a severed string.
    cut = text[: limit - 1].rstrip()
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return f"{cut}…"


def _job_line(job: _JobLike) -> str:
    title = _truncate(str(getattr(job, "title", "") or ""))
    company = str(getattr(job, "company", "") or "").strip()
    return f"• {title} — {company}" if company else f"• {title}"


def x_length(text: str, url: str) -> int:
    """Length of `text` as X will count it, with `url` billed at 23 chars.

    Exposed (and tested) separately because "does this fit in a tweet" is the
    one rule that decides how many jobs the digest can list.
    """
    if not url or url not in text:
        return len(text)
    return len(text) - len(url) + X_URL_LENGTH


def _render(lines: list[str], total: int, url: str) -> str:
    shown = len(lines)
    header = _HEADER_SINGULAR if total == 1 else _HEADER_PLURAL.format(count=total)
    body = list(lines)
    if total > shown:
        body.append(f"+{total - shown} more")
    return "\n".join([header, "", *body, "", _CALL_TO_ACTION.format(url=url)])


def build_digest(
    jobs: Iterable[_JobLike],
    site_url: str,
    max_jobs: int = 5,
) -> str | None:
    """Return the post text, or None when there are no jobs to announce.

    Lists up to `max_jobs` titles, then drops lines one at a time until the
    result fits X's 280-character budget, replacing what it dropped with a
    "+N more" line so the reader still knows the full count. Returning None
    rather than an empty-sounding post matters: the scrapers legitimately find
    nothing on a quiet run, and "0 new jobs today" is not worth posting.
    """
    all_jobs = [j for j in jobs]
    if not all_jobs:
        return None

    total = len(all_jobs)
    lines = [_job_line(j) for j in all_jobs[:max_jobs]]

    # Shrink until it fits. The header, the "+N more" line and the call to
    # action are never dropped - they are what makes the post usable at all.
    while lines:
        text = _render(lines, total, site_url)
        if x_length(text, site_url) <= X_CHARACTER_LIMIT:
            return text
        lines.pop()

    # Every individual line was too long to fit alongside the header and link
    # (pathological titles). Fall back to the count plus the link, which is
    # still a valid, useful post.
    return _render([], total, site_url)
