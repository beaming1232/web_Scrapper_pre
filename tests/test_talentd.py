"""Tests for scrapers/sources/talentd.py.

No network access: fetch() is not exercised here (it's a thin httpx
wrapper); these tests cover parse()'s JSON-LD extraction (from a realistic
RSC-streamed fixture matching the real site's verified format) and
normalize()'s field mapping directly, plus the apply-link classification
logic feeding pipeline/filter.py's real external-only filter.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from db.models import ApplyType, JobSchema
from pipeline.filter import apply_external_filter
from scrapers.sources.talentd import TalentdSource, _classify_apply_type, _is_software_related


def _iso_hours_ago(hours: float) -> str:
    """ISO 8601 timestamp `hours` in the past, in the same "...Z" shape
    talentd's datePosted uses. Used instead of a hardcoded date so tests
    stay valid regardless of when they're actually run.
    """
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _make_detail_html(
    job_ld: dict,
    apply_href: str = "https://careers.acme.com/jobs/1",
    description_html: str = "<h3>Role</h3><p>Do stuff.</p>",
    content_div_suffix: str = "baQN3",
    extra_blank_links: str = "",
) -> str:
    """Build a minimal HTML page in the same shape talentd.in actually
    serves, verified directly against a real fetched page:

    - The JobPosting JSON-LD lives inside an `@graph` array alongside a
      BreadcrumbList, delivered as a single self-contained
      `self.__next_f.push([1,"..."])` chunk (one level of JS string
      escaping — `json.dumps` twice here mirrors exactly what the real
      page does: once for the JSON document, once for the JS string
      literal it's embedded as).
    - The real Apply destination is a plain, unescaped `<a target="_blank">`
      elsewhere in the literal DOM — deliberately NOT the same as the
      JSON-LD's own `url` field.
    - The full description lives in a `jobContent_jobContent__{hash}` div,
      literal HTML, separate from the JSON-LD's own (truncated) description.
    """
    graph_obj = {
        "@context": "https://schema.org",
        "@graph": [
            job_ld,
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home"},
                ],
            },
        ],
    }
    # Minified (no spaces after , / :), matching the real production JSON
    # captured directly from a live talentd.in page.
    push_payload = json.dumps(graph_obj, separators=(",", ":"))

    def push(payload: str) -> str:
        return f'<script>self.__next_f.push([1,{json.dumps(payload)}])</script>'

    apply_link = f'<a href="{apply_href}" target="_blank" rel="noopener noreferrer">Apply Now</a>'
    desc_div = f'<div class="jobContent_jobContent__{content_div_suffix}">{description_html}</div>'
    return (
        f"<html><body>{push(push_payload)}{extra_blank_links}"
        f"{apply_link}{desc_div}</body></html>"
    )


BASE_JOB_LD = {
    "@type": "JobPosting",
    "@id": "https://www.talentd.in/jobs/acme-is-hiring-backend-engineer-bangalore-abcd#jobposting",
    "title": "Backend Engineer",
    "description": "Job DescriptionAcme is hiring a backend engineer&hellip;",
    "employmentType": "full-time",
    "jobLocation": [
        {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Bangalore",
                "addressRegion": "Karnataka",
                "addressCountry": "IN",
            },
        }
    ],
    "hiringOrganization": {"@type": "Organization", "name": "Acme Corp"},
    "url": "https://www.talentd.in/jobs/acme-is-hiring-backend-engineer-bangalore-abcd",
    "datePosted": _iso_hours_ago(1),  # 1h ago: comfortably inside the default 24h window
    "validThrough": "2026-11-09T10:26:11.000Z",
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "INR",
        "value": {"@type": "QuantitativeValue", "minValue": 1000000, "maxValue": 2000000, "unitText": "YEAR"},
    },
    "skills": "Python, Django, PostgreSQL",
    "experienceRequirements": "2-4 years",
}

SLUG = "acme-is-hiring-backend-engineer-bangalore-abcd"
PAGE_URL = f"https://www.talentd.in/jobs/{SLUG}"


def _normalize(
    job_ld_overrides: dict,
    apply_href: str = "https://careers.acme.com/jobs/1",
    description_html: str = "<h3>Role</h3><p>Do stuff.</p>",
    content_div_suffix: str = "baQN3",
    extra_blank_links: str = "",
) -> dict:
    job_ld = {**BASE_JOB_LD, **job_ld_overrides}
    html = _make_detail_html(
        job_ld,
        apply_href=apply_href,
        description_html=description_html,
        content_div_suffix=content_div_suffix,
        extra_blank_links=extra_blank_links,
    )
    source = TalentdSource()
    records = source.parse([{"url": PAGE_URL, "html": html}])
    assert len(records) == 1
    return source.normalize(records[0])


# --------------------------------------------------------------------------
# Salary present / absent
# --------------------------------------------------------------------------
def test_listing_with_salary_present():
    result = _normalize({})
    assert result["has_salary"] is True
    assert result["salary_min"] == 1_000_000
    assert result["salary_max"] == 2_000_000
    assert result["salary_period"] == "annual"
    assert result["salary_currency"] == "INR"
    assert "salary_min" not in result["source_fields_missing"]


def test_listing_with_no_salary():
    result = _normalize({"baseSalary": None})
    assert result["has_salary"] is False
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["salary_raw"] is None
    assert "salary_min" in result["source_fields_missing"]
    assert "salary_max" in result["source_fields_missing"]
    assert "salary_raw" in result["source_fields_missing"]


# --------------------------------------------------------------------------
# employment_type mapping
# --------------------------------------------------------------------------
def test_employment_type_full_time_confirmed_mapping():
    """The only value actually observed live at implementation time."""
    result = _normalize({"employmentType": "full-time"})
    assert result["employment_type"] == "full-time"


def test_employment_type_speculative_values_pending_live_confirmation():
    """These raw strings have NOT been observed on a real talentd.in
    listing yet (only "full-time" has) — the mapping table's entries for
    them are best-effort guesses at likely schema.org-style values. If
    real internship/part-time/contract postings ever get sampled and use a
    different raw string, this test (not the scraper's correctness on
    full-time listings) is what should be revisited.
    """
    assert _normalize({"employmentType": "internship"})["employment_type"] == "internship"
    assert _normalize({"employmentType": "part-time"})["employment_type"] == "part-time"
    assert _normalize({"employmentType": "contract"})["employment_type"] == "contract"


def test_employment_type_missing_is_flagged():
    result = _normalize({"employmentType": None})
    assert result["employment_type"] is None
    assert "employment_type" in result["source_fields_missing"]


def test_employment_type_multi_value_string_picks_canonical_token():
    """Regression test: verified live on a real talentd listing (Amazon,
    "Central Operations Support Executive"), employmentType can be a
    comma-separated multi-value string like "full-time, remote" — the
    non-canonical "remote" token must be skipped, not concatenated into a
    garbage compound value, and its signal should still reach is_remote.
    """
    result = _normalize({"employmentType": "full-time, remote", "title": "Remote Backend Engineer"})
    assert result["employment_type"] == "full-time"
    assert result["is_remote"] is True


# --------------------------------------------------------------------------
# Apply link classification
# --------------------------------------------------------------------------
def test_apply_link_resolves_externally():
    result = _normalize({}, apply_href="https://careers.acme.com/jobs/12345")
    assert result["apply_type"] == ApplyType.EXTERNAL.value
    assert result["raw_apply_url"] == "https://careers.acme.com/jobs/12345"

    # And end-to-end through the real (untouched) pipeline filter:
    job = JobSchema(id="x", source="talentd", fingerprint="fp", **result)
    kept = apply_external_filter([job])
    assert len(kept) == 1
    assert kept[0].is_external is True


def test_apply_link_stays_on_talentd_is_filtered_out():
    result = _normalize({}, apply_href="https://www.talentd.in/jobs/some-other-posting")
    assert result["apply_type"] == ApplyType.DIRECT.value

    job = JobSchema(id="x", source="talentd", fingerprint="fp", **result)
    kept = apply_external_filter([job])
    assert kept == []
    assert job.is_external is False


def test_apply_link_to_known_aggregator_is_not_external():
    result = _normalize({}, apply_href="https://www.naukri.com/job-listings-1")
    assert result["apply_type"] == ApplyType.UNKNOWN.value

    job = JobSchema(id="x", source="talentd", fingerprint="fp", **result)
    kept = apply_external_filter([job])
    assert kept == []


def test_classify_apply_type_directly():
    assert _classify_apply_type("https://careers.acme.com/jobs/123") == "EXTERNAL"
    assert _classify_apply_type("https://acme.wd108.myworkdayjobs.com/job/1") == "EXTERNAL"
    assert _classify_apply_type("https://www.talentd.in/jobs/whatever") == "DIRECT"
    assert _classify_apply_type("https://www.linkedin.com/jobs/view/1/") == "UNKNOWN"
    assert _classify_apply_type("https://www.naukri.com/job-listings-1") == "UNKNOWN"
    assert _classify_apply_type("") == "UNKNOWN"
    assert _classify_apply_type(None) == "UNKNOWN"


def test_apply_url_is_dom_link_not_json_ld_canonical_url():
    """Regression guard for the single most important correctness point in
    this scraper: the JSON-LD's own `url` field is talentd's own canonical
    page URL, NOT the apply destination. normalize() must use the DOM
    Apply button's href, never job_ld["url"].
    """
    result = _normalize(
        {"url": "https://www.talentd.in/jobs/acme-is-hiring-backend-engineer-bangalore-abcd"},
        apply_href="https://careers.acme.com/apply/9999",
    )
    assert result["raw_apply_url"] == "https://careers.acme.com/apply/9999"
    assert result["raw_apply_url"] != BASE_JOB_LD["url"]


def test_apply_url_prefers_labelled_link_over_other_blank_targets():
    """The page may contain other target="_blank" links (e.g. a "View
    company" link) — extraction should prefer the one whose text mentions
    "apply" rather than grabbing the first target="_blank" anchor blindly.
    """
    result = _normalize(
        {},
        apply_href="https://careers.acme.com/apply/42",
        extra_blank_links='<a href="https://www.talentd.in/companies/acme" target="_blank">View Company</a>',
    )
    assert result["raw_apply_url"] == "https://careers.acme.com/apply/42"


# --------------------------------------------------------------------------
# is_remote heuristic — always flagged missing (no structured source field)
# --------------------------------------------------------------------------
def test_is_remote_true_from_remote_keyword():
    result = _normalize({"title": "Remote Backend Engineer"})
    assert result["is_remote"] is True
    assert "is_remote" in result["source_fields_missing"]


def test_is_remote_false_for_hybrid_even_if_remote_appears():
    result = _normalize({"title": "Remote-friendly Backend Engineer (Hybrid)"})
    assert result["is_remote"] is False
    assert "is_remote" in result["source_fields_missing"]


def test_is_remote_default_false_when_no_signal():
    result = _normalize({"title": "Backend Engineer"})
    assert result["is_remote"] is False
    assert "is_remote" in result["source_fields_missing"]


# --------------------------------------------------------------------------
# Description extraction (hashed class prefix matching)
# --------------------------------------------------------------------------
def test_description_extracted_from_hashed_content_div():
    result = _normalize(
        {}, description_html="<h3>Role Summary</h3><p>Build things.</p>", content_div_suffix="baQN3"
    )
    assert result["description_available"] is True
    assert "Role Summary" in result["description_original"]
    assert "Build things." in result["description_original"]
    assert "<h3>" not in result["description_original"]


def test_description_extraction_not_pinned_to_one_build_hash():
    """A different (fake) build-hash suffix must still be found — proves
    substring/prefix matching, not exact-class matching.
    """
    result = _normalize(
        {}, description_html="<p>Different build, same structure.</p>", content_div_suffix="xk9Zq"
    )
    assert result["description_available"] is True
    assert "Different build, same structure." in result["description_original"]


def test_description_falls_back_to_json_ld_snippet_when_div_missing():
    job_ld = {**BASE_JOB_LD, "description": "Truncated SEO snippet&hellip;"}
    html = _make_detail_html(job_ld).replace(
        '<div class="jobContent_jobContent__baQN3"><h3>Role</h3><p>Do stuff.</p></div>', ""
    )
    source = TalentdSource()
    records = source.parse([{"url": PAGE_URL, "html": html}])
    result = source.normalize(records[0])
    assert result["description_available"] is True
    assert "Truncated SEO snippet" in result["description_original"]


# --------------------------------------------------------------------------
# Seniority
# --------------------------------------------------------------------------
def test_seniority_inferred_from_experience_requirements():
    assert _normalize({"experienceRequirements": "0-2 years"})["seniority"] == "fresher"
    assert _normalize({"experienceRequirements": "2-4 years"})["seniority"] == "junior"
    assert _normalize({"experienceRequirements": "5-8 years"})["seniority"] == "mid"
    assert _normalize({"experienceRequirements": "8-10 years"})["seniority"] == "senior"


def test_seniority_falls_back_to_fresher_keyword_in_title():
    result = _normalize({"experienceRequirements": None, "title": "Fresher Software Engineer"})
    assert result["seniority"] == "fresher"


def test_seniority_missing_when_no_signal_at_all():
    result = _normalize({"experienceRequirements": None, "title": "Software Engineer"})
    assert result["seniority"] is None
    assert "seniority" in result["source_fields_missing"]


# --------------------------------------------------------------------------
# Missing-field fallback
# --------------------------------------------------------------------------
def test_missing_fields_fallback_populates_source_fields_missing():
    result = _normalize(
        {
            "jobLocation": None,
            "employmentType": None,
            "experienceRequirements": None,
            "skills": None,
            "title": "Backend Engineer",
        }
    )
    assert result["location"] is None
    assert result["employment_type"] is None
    assert result["seniority"] is None
    assert result["tags"] == []
    for field in ("location", "employment_type", "seniority", "tags"):
        assert field in result["source_fields_missing"]
    # Title/company/apply link still survive even when everything else is missing.
    assert result["title"] == "Backend Engineer"
    assert result["company"] == "Acme Corp"
    assert result["raw_apply_url"]


# --------------------------------------------------------------------------
# Role scope — software/IT-specific only (this aggregator's own decision,
# not talentd.in's — see module docstring point 9)
# --------------------------------------------------------------------------
def _parse_one(job_ld_overrides: dict) -> list[dict]:
    job_ld = {**BASE_JOB_LD, **job_ld_overrides}
    html = _make_detail_html(job_ld)
    source = TalentdSource()
    return source.parse([{"url": PAGE_URL, "html": html}])


def test_software_job_is_kept():
    assert len(_parse_one({"title": "Backend Software Engineer"})) == 1


def test_bpo_customer_support_job_is_dropped():
    assert _parse_one({"title": "Non-Voice Customer Support Executive", "skills": "Communication"}) == []


def test_sales_marketing_job_is_dropped():
    assert _parse_one({"title": "Business Development Executive", "skills": "Communication, Negotiation"}) == []


def test_hr_admin_job_is_dropped():
    assert _parse_one({"title": "HR Executive - Talent Acquisition", "skills": "Recruitment"}) == []


def test_software_sales_title_exclude_wins_over_include():
    """"Software Sales Executive" is a sales role, not an engineering
    one — the exclude match must win even though "software" also appears.
    """
    assert _parse_one({"title": "Software Sales Executive"}) == []


def test_generic_title_with_no_software_signal_is_dropped():
    """Not one of the three explicitly-excluded categories, but also no
    software/IT signal at all — dropped for lack of a positive match, per
    the "software specific and related" scoping requirement.
    """
    assert _parse_one({"title": "Associate Trainee", "skills": ""}) == []


def test_is_software_related_directly():
    assert _is_software_related("Full Stack Developer", "") is True
    assert _is_software_related("Data Scientist", "") is True
    assert _is_software_related("QA Engineer", "") is True
    assert _is_software_related("Generic Trainee", "") is False
    assert _is_software_related("Customer Support Executive", "") is False
    assert _is_software_related("Software Sales Executive", "") is False
    # The include list matches role/title vocabulary ("developer",
    # "backend engineer", etc.), not raw tech-stack names — a skills list
    # of bare technology names with no role-type wording doesn't count as
    # a signal on its own, and neither does a bare "Engineer" title
    # (that alone doesn't distinguish software engineering from
    # core-engineering/mechanical roles, a separate talentd.in category).
    assert _is_software_related("Associate", "Python, Django, REST APIs") is False
    assert _is_software_related("Engineer", "Python, Django, REST APIs") is False
    # But a skills list that itself names a role ("Backend Developer" as a
    # skill tag) is still picked up, since include-matching runs over the
    # combined title+skills text.
    assert _is_software_related("Associate", "Backend Developer, Python") is True


# --------------------------------------------------------------------------
# India-only scope
# --------------------------------------------------------------------------
def test_non_india_job_is_dropped_when_country_present_and_wrong():
    job_ld = {**BASE_JOB_LD}
    job_ld["jobLocation"] = [
        {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "London", "addressCountry": "GB"}}
    ]
    html = _make_detail_html(job_ld)
    source = TalentdSource()
    records = source.parse([{"url": PAGE_URL, "html": html}])
    assert records == []


def test_job_is_kept_when_country_field_simply_absent():
    """Absence of addressCountry is not evidence of being non-Indian on
    this source — only an explicit non-"IN" value should drop a listing.
    """
    job_ld = {**BASE_JOB_LD}
    job_ld["jobLocation"] = [{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Bangalore"}}]
    html = _make_detail_html(job_ld)
    source = TalentdSource()
    records = source.parse([{"url": PAGE_URL, "html": html}])
    assert len(records) == 1


# --------------------------------------------------------------------------
# Recency window (parse() is the authoritative check; fetch()'s
# lastmod-based early-stop is only an optimization and isn't exercised here
# since it needs live network access)
# --------------------------------------------------------------------------
def test_recent_job_is_kept():
    job_ld = {**BASE_JOB_LD, "datePosted": _iso_hours_ago(2)}
    html = _make_detail_html(job_ld)
    source = TalentdSource()  # default max_job_age_hours=24
    records = source.parse([{"url": PAGE_URL, "html": html}])
    assert len(records) == 1


def test_stale_job_is_dropped_by_default_window():
    job_ld = {**BASE_JOB_LD, "datePosted": _iso_hours_ago(48)}
    html = _make_detail_html(job_ld)
    source = TalentdSource()
    records = source.parse([{"url": PAGE_URL, "html": html}])
    assert records == []


def test_job_with_no_posted_at_is_dropped():
    job_ld = {**BASE_JOB_LD, "datePosted": None}
    html = _make_detail_html(job_ld)
    source = TalentdSource()
    records = source.parse([{"url": PAGE_URL, "html": html}])
    assert records == []


def test_custom_max_job_age_hours_is_respected():
    job_ld = {**BASE_JOB_LD, "datePosted": _iso_hours_ago(5)}
    html = _make_detail_html(job_ld)
    page = {"url": PAGE_URL, "html": html}

    # 5h-old posting: kept with a 6h window, dropped with a 3h window.
    assert len(TalentdSource(max_job_age_hours=6).parse([page])) == 1
    assert TalentdSource(max_job_age_hours=3).parse([page]) == []


# --------------------------------------------------------------------------
# JSON-LD extraction against the real, verified RSC-stream format
# --------------------------------------------------------------------------
def test_json_ld_extraction_from_graph_with_breadcrumb_sibling():
    """Verified directly against a real fetched page: the JobPosting object
    is nested inside `@graph` alongside a BreadcrumbList, not at the JSON
    document's top level. Every _normalize() call above already exercises
    this shape via _make_detail_html; this test asserts it explicitly.
    """
    result = _normalize({"title": "Extraction Check Software Engineer"})
    assert result["title"] == "Extraction Check Software Engineer"


def test_page_with_no_job_posting_ld_yields_no_records():
    """A sitemap hub page (or any other non-posting page) has no JobPosting
    JSON-LD at all — parse() must drop it rather than raise.
    """
    html = "<html><body><script>self.__next_f.push([1,\"not json at all\"])</script></body></html>"
    source = TalentdSource()
    records = source.parse([{"url": "https://www.talentd.in/jobs/it-software-jobs", "html": html}])
    assert records == []
