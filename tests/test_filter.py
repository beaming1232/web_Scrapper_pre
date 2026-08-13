"""Tests for pipeline/filter.py, including the post-resolution aggregator
recheck (revalidate_after_resolution) that closes the gap a scraper's
pre-resolution apply_type classification can't: a raw apply URL that
doesn't look like an aggregator but whose redirect chain resolves to one.
"""
from __future__ import annotations

from db.models import ApplyType, JobSchema
from pipeline.filter import (
    apply_external_filter,
    is_aggregator_domain,
    revalidate_after_resolution,
)


def _job(**overrides) -> JobSchema:
    base = dict(
        id="x",
        source="test_source",
        fingerprint="fp",
        title="Backend Engineer",
        company="Acme",
        raw_apply_url="https://track.acme-jobs.example/r/123",
        apply_type=ApplyType.EXTERNAL,
    )
    base.update(overrides)
    return JobSchema(**base)


def test_is_aggregator_domain_matches_known_boards_and_subdomains():
    assert is_aggregator_domain("linkedin.com") is True
    assert is_aggregator_domain("www.linkedin.com") is True
    assert is_aggregator_domain("jobs.linkedin.com") is True
    assert is_aggregator_domain("careers.acme.com") is False
    assert is_aggregator_domain(None) is False
    assert is_aggregator_domain("") is False


def test_apply_external_filter_pre_resolution_unaffected_by_this_change():
    job = _job(apply_type=ApplyType.EXTERNAL)
    kept = apply_external_filter([job])
    assert len(kept) == 1
    assert kept[0].is_external is True


def test_revalidate_downgrades_when_resolved_domain_is_aggregator():
    """The exact gap this closes: apply_type looked EXTERNAL pre-resolution
    (a tracker link gives no hint), but the redirect chain lands on a
    known aggregator.
    """
    job = _job(is_external=True, resolved_domain="www.linkedin.com")
    result = revalidate_after_resolution([job])
    assert len(result) == 1
    assert result[0].is_external is False


def test_revalidate_keeps_genuine_external_domain():
    job = _job(is_external=True, resolved_domain="careers.acme.com")
    result = revalidate_after_resolution([job])
    assert result[0].is_external is True


def test_revalidate_leaves_unresolved_urls_alone():
    """A failed resolution (resolved_domain=None) is not evidence of
    anything — don't punish it.
    """
    job = _job(is_external=True, resolved_domain=None)
    result = revalidate_after_resolution([job])
    assert result[0].is_external is True


def test_revalidate_does_not_resurrect_already_excluded_jobs():
    job = _job(is_external=False, resolved_domain="careers.acme.com")
    result = revalidate_after_resolution([job])
    assert result[0].is_external is False
