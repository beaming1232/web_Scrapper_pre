"""Tests for scrapers/sources/jobfound.py.

No network access: fetch() is not exercised here (it's a thin httpx
wrapper); these tests cover parse()'s Flight-payload extraction and
normalize()'s field mapping directly, plus the apply-link classification
logic feeding pipeline/filter.py's real external-only filter.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from db.models import ApplyType, JobSchema
from pipeline.filter import apply_external_filter
from scrapers.sources.jobfound import JobfoundSource, _classify_apply_type


def _iso_hours_ago(hours: float) -> str:
    """ISO 8601 timestamp `hours` in the past, in the same "...Z" shape
    Jobfound's postedAt uses. Used instead of a hardcoded date so tests
    stay valid regardless of when they're actually run — parse() now
    drops anything outside its recency window (default 24h).
    """
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _make_detail_html(job: dict, description_html: str = "<h3>Role</h3><p>Do stuff.</p>") -> str:
    """Build a minimal HTML page in the same shape jobfound.org actually
    serves: a `self.__next_f.push([1,"..."])` call carrying the
    `initialJob` JSON (with description pointing at a "$21" reference),
    followed by a second push carrying the row-21 text chunk.
    """
    job_with_ref = {**job, "description": "$21"}
    # Deliberately NOT newline-separated: verified against the live site
    # that consecutive Flight rows can butt directly against each other
    # with zero delimiter (e.g. `..."industry":"X"}21:T9bf,<h3>...` with no
    # `\n` anywhere near the boundary). _resolve_flight_text_row locates
    # rows by their declared byte length, not by line splitting, precisely
    # because of this.
    initial_job_chunk = (
        f'0:["$","$L2",null,{{"initialJob":{json.dumps(job_with_ref)},"similarJobs":[]}}]'
    )
    text_chunk = f"21:T{len(description_html.encode('utf-8')):x},{description_html}"

    def push(payload: str) -> str:
        return f'<script>self.__next_f.push([1,{json.dumps(payload)}])</script>'

    return f"<html><body>{push(initial_job_chunk)}{push(text_chunk)}</body></html>"


BASE_JOB = {
    "title": "Backend Engineer",
    "slug": "acme-is-hiring-for-backend-engineer-bangalore-india-7-august-2026",
    "companyName": "Acme Corp",
    "jobType": "Full-time",
    "experience": "2-4",
    "domain": "Software Engineering",
    "location": "Bangalore",
    "country": "India",
    "skills": "Python, Django, PostgreSQL",
    "applyUrl": "https://careers.acme.com/jobs/12345",
    "workplaceType": "onsite",
    "postedAt": _iso_hours_ago(1),  # 1h ago: comfortably inside the default 24h window
    "expiresAt": None,
    "isBlurred": False,
}


def _normalize(job_overrides: dict, description_html: str = "<h3>Role</h3><p>Do stuff.</p>") -> dict:
    job = {**BASE_JOB, **job_overrides}
    html = _make_detail_html(job, description_html)
    source = JobfoundSource()
    records = source.parse([{"url": f"https://www.jobfound.org/job/{job['slug']}", "html": html}])
    assert len(records) == 1
    return source.normalize(records[0])


# --------------------------------------------------------------------------
# Salary present / absent
# --------------------------------------------------------------------------
def test_listing_with_salary_present():
    result = _normalize({"salary": "10-20 LPA"})
    assert result["has_salary"] is True
    assert result["salary_min"] == 1_000_000
    assert result["salary_max"] == 2_000_000
    assert result["salary_period"] == "annual"
    assert result["salary_raw"] == "10-20 LPA"
    assert "salary_min" not in result["source_fields_missing"]


def test_listing_with_no_salary():
    result = _normalize({"salary": None})
    assert result["has_salary"] is False
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["salary_raw"] is None
    assert "salary_min" in result["source_fields_missing"]
    assert "salary_max" in result["source_fields_missing"]
    assert "salary_raw" in result["source_fields_missing"]


# --------------------------------------------------------------------------
# Apply link classification
# --------------------------------------------------------------------------
def test_apply_link_resolves_externally():
    result = _normalize({"applyUrl": "https://careers.acme.com/jobs/12345"})
    assert result["apply_type"] == ApplyType.EXTERNAL.value
    assert result["raw_apply_url"] == "https://careers.acme.com/jobs/12345"

    # And end-to-end through the real (untouched) pipeline filter:
    job = JobSchema(id="x", source="jobfound", fingerprint="fp", **result)
    kept = apply_external_filter([job])
    assert len(kept) == 1
    assert kept[0].is_external is True


def test_apply_link_stays_on_jobfound_is_filtered_out():
    result = _normalize(
        {"applyUrl": "https://jobfound.org/job/acme-is-hiring-for-backend-engineer-bangalore"}
    )
    assert result["apply_type"] != ApplyType.EXTERNAL.value

    job = JobSchema(id="x", source="jobfound", fingerprint="fp", **result)
    kept = apply_external_filter([job])
    assert kept == []
    # is_external is only ever stamped True by the filter for survivors;
    # a dropped job's default (False) is what would be persisted if a
    # caller ignored the filter's return value.
    assert job.is_external is False


def test_apply_link_to_known_aggregator_is_not_external():
    """LinkedIn (and similar) is a job board, not the hiring company's own
    page — classify as UNKNOWN, not EXTERNAL, so it gets filtered out too.
    """
    result = _normalize({"applyUrl": "https://www.linkedin.com/jobs/view/4448084374/"})
    assert result["apply_type"] == ApplyType.UNKNOWN.value

    job = JobSchema(id="x", source="jobfound", fingerprint="fp", **result)
    kept = apply_external_filter([job])
    assert kept == []


def test_classify_apply_type_directly():
    assert _classify_apply_type("https://careers.netapp.com/job/123") == "EXTERNAL"
    assert _classify_apply_type("https://job-boards.greenhouse.io/gympass/jobs/1") == "EXTERNAL"
    assert _classify_apply_type("https://www.jobfound.org/job/whatever") == "DIRECT"
    assert _classify_apply_type("https://www.linkedin.com/jobs/view/1/") == "UNKNOWN"
    assert _classify_apply_type("https://www.naukri.com/job-listings-1") == "UNKNOWN"
    assert _classify_apply_type("") == "UNKNOWN"
    assert _classify_apply_type(None) == "UNKNOWN"


# --------------------------------------------------------------------------
# Other field mapping
# --------------------------------------------------------------------------
def test_description_extracted_as_plain_text():
    result = _normalize({}, description_html="<h3>Role Summary</h3><p>Build things.</p>")
    assert result["description_available"] is True
    assert "Role Summary" in result["description_original"]
    assert "Build things." in result["description_original"]
    assert "<h3>" not in result["description_original"]


def test_description_inline_in_initial_job_not_a_flight_ref():
    """Some listings embed the description HTML directly in initialJob
    (observed live: Algoleap Technologies) instead of streaming it as a
    separate "$21"-style Flight reference. Both shapes must work.
    """
    inline_html = "<h3>Responsibilities</h3><p>Ship things.</p>"
    job = {**BASE_JOB, "description": inline_html}
    # Build directly rather than via _make_detail_html (which always injects
    # a "$21" ref) so `description` stays inline as the literal HTML.
    payload = f'0:["$","$L2",null,{{"initialJob":{json.dumps(job)},"similarJobs":[]}}]'
    html = (
        f'<html><body><script>self.__next_f.push([1,{json.dumps(payload)}])</script></body></html>'
    )
    source = JobfoundSource()
    records = source.parse([{"url": "https://www.jobfound.org/job/x", "html": html}])
    assert len(records) == 1
    result = source.normalize(records[0])
    assert result["description_available"] is True
    assert "Responsibilities" in result["description_original"]
    assert "Ship things." in result["description_original"]


def test_posted_at_parses_iso_timestamp():
    posted_str = _iso_hours_ago(2)
    result = _normalize({"postedAt": posted_str})
    assert result["posted_at"] is not None
    # Round-trips to the same instant (within float-precision slack from
    # the millisecond-truncated ISO string).
    expected = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
    assert abs((result["posted_at"] - expected).total_seconds()) < 1


def test_seniority_inferred_from_experience():
    assert _normalize({"experience": "0"})["seniority"] == "fresher"
    assert _normalize({"experience": "2-4"})["seniority"] == "junior"
    assert _normalize({"experience": "5+"})["seniority"] == "mid"


def test_tags_include_skills_and_role_category():
    result = _normalize({"skills": "Python, Django", "domain": "Backend"})
    assert "Python" in result["tags"]
    assert "Django" in result["tags"]
    assert "Backend" in result["tags"]


def test_non_india_job_is_dropped_by_parse():
    job = {**BASE_JOB, "country": "UK", "description": "$21"}
    html = _make_detail_html(job)
    source = JobfoundSource()
    records = source.parse([{"url": "https://www.jobfound.org/job/uk-job", "html": html}])
    assert records == []


def test_missing_location_and_employment_type_are_flagged():
    result = _normalize({"location": None, "jobType": None})
    assert result["location"] is None
    assert result["employment_type"] is None
    assert "location" in result["source_fields_missing"]
    assert "employment_type" in result["source_fields_missing"]


# --------------------------------------------------------------------------
# 24h recency window (parse() is the authoritative check; fetch()'s
# early-stop is only an optimization and isn't exercised here since it
# needs live network access)
# --------------------------------------------------------------------------
def test_recent_india_job_is_kept():
    job = {**BASE_JOB, "postedAt": _iso_hours_ago(2), "description": "$21"}
    html = _make_detail_html(job)
    source = JobfoundSource()  # default max_job_age_hours=24
    records = source.parse([{"url": "https://www.jobfound.org/job/x", "html": html}])
    assert len(records) == 1


def test_stale_india_job_is_dropped_by_default_24h_window():
    job = {**BASE_JOB, "postedAt": _iso_hours_ago(48), "description": "$21"}
    html = _make_detail_html(job)
    source = JobfoundSource()
    records = source.parse([{"url": "https://www.jobfound.org/job/x", "html": html}])
    assert records == []


def test_job_with_no_posted_at_is_dropped():
    """Can't confirm recency for a job we can't date, so it's excluded
    rather than assumed-recent.
    """
    job = {**BASE_JOB, "postedAt": None, "description": "$21"}
    html = _make_detail_html(job)
    source = JobfoundSource()
    records = source.parse([{"url": "https://www.jobfound.org/job/x", "html": html}])
    assert records == []


def test_custom_max_job_age_hours_is_respected():
    job = {**BASE_JOB, "postedAt": _iso_hours_ago(5), "description": "$21"}
    html = _make_detail_html(job)
    page = {"url": "https://www.jobfound.org/job/x", "html": html}

    # 5h-old posting: kept with a 6h window, dropped with a 3h window.
    assert len(JobfoundSource(max_job_age_hours=6).parse([page])) == 1
    assert JobfoundSource(max_job_age_hours=3).parse([page]) == []
