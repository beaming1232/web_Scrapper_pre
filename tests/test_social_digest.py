"""Tests for social/digest.py.

The load-bearing rule here is X's 280-character budget: the whole reason the
digest lists job *titles* and one link to our own site, rather than five apply
links, is that the latter cannot physically fit. If
`test_digest_always_fits_x_limit_even_with_many_long_jobs` goes red, the digest
has silently become unpostable on X.
"""
from __future__ import annotations

from dataclasses import dataclass

from social.digest import (
    X_CHARACTER_LIMIT,
    X_URL_LENGTH,
    build_digest,
    x_length,
)

SITE = "https://web-scrapper-pre.vercel.app"


@dataclass
class FakeJob:
    title: str
    company: str


def _jobs(n: int, title: str = "Backend Engineer", company: str = "Acme") -> list[FakeJob]:
    return [FakeJob(title=f"{title} {i}", company=company) for i in range(1, n + 1)]


def test_no_jobs_returns_none_rather_than_an_empty_post():
    """A quiet scrape run is normal; "0 new jobs today" isn't worth posting."""
    assert build_digest([], SITE) is None


def test_digest_lists_titles_and_links_to_our_own_site():
    message = build_digest(_jobs(3), SITE)

    assert message is not None
    assert "Backend Engineer 1 — Acme" in message
    assert "Backend Engineer 3 — Acme" in message
    assert SITE in message


def test_digest_never_contains_an_employer_apply_link():
    """The link must point at us, not the employer.

    A post carrying the direct apply URL sends the reader straight past the
    site: no pageview, no ad impression. That trade is the entire reason this
    format lists titles instead of links.
    """
    jobs = [FakeJob(title="SDE Intern", company="Spyne")]
    message = build_digest(jobs, SITE)

    assert message is not None
    assert message.count("http") == 1
    assert SITE in message


def test_x_length_bills_urls_at_23_characters():
    """X counts every URL as 23 chars after t.co wrapping, however long it is.

    Counting len(url) instead would make a long URL look unpostable and drop
    job lines that would in fact have fit.
    """
    long_url = "https://example.com/" + "a" * 200
    text = f"hello {long_url}"

    assert x_length(text, long_url) == len("hello ") + X_URL_LENGTH
    assert x_length(text, long_url) < len(text)


def test_digest_always_fits_x_limit_even_with_many_long_jobs():
    jobs = [
        FakeJob(
            title="Senior Staff Software Development Engineer, Platform Infrastructure",
            company="A Very Long Company Name Private Limited",
        )
        for _ in range(12)
    ]

    message = build_digest(jobs, SITE, max_jobs=12)

    assert message is not None
    assert x_length(message, SITE) <= X_CHARACTER_LIMIT


def test_dropped_jobs_are_reported_as_plus_n_more():
    """Trimming to fit must not silently understate how many jobs there are."""
    jobs = [
        FakeJob(title="Senior Software Development Engineer " + "x" * 20, company="Company")
        for _ in range(9)
    ]

    message = build_digest(jobs, SITE, max_jobs=9)

    assert message is not None
    listed = sum(1 for line in message.splitlines() if line.startswith("• "))
    assert listed < 9
    assert f"+{9 - listed} more" in message
    assert "9 new tech jobs" in message


def test_header_is_singular_for_one_job():
    message = build_digest(_jobs(1), SITE)

    assert message is not None
    assert "1 new tech job in India today" in message
    assert "jobs in India" not in message


def test_message_is_plain_text_with_no_platform_markup():
    """One message goes verbatim to X, WhatsApp and Telegram.

    Their bold syntaxes differ (`*x*` vs `**x**` vs none), so any markup would
    render as literal asterisks on at least one of them.
    """
    message = build_digest(_jobs(5), SITE)

    assert message is not None
    assert "*" not in message
    assert "_" not in message
    assert "<" not in message


def test_long_title_is_truncated_not_dropped():
    jobs = [FakeJob(title="A" * 200, company="Acme")]

    message = build_digest(jobs, SITE)

    assert message is not None
    assert "…" in message
    assert x_length(message, SITE) <= X_CHARACTER_LIMIT
