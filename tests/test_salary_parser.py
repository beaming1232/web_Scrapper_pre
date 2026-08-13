"""Unit tests for pipeline/salary_parser.py."""
from __future__ import annotations

import pytest

from pipeline.salary_parser import parse_salary


def test_lpa_range_with_rupee_symbol():
    result = parse_salary("₹8-12 LPA")
    assert result.salary_min == 800_000
    assert result.salary_max == 1_200_000
    assert result.salary_period == "annual"
    assert result.has_salary is True


def test_lakhs_per_annum_words():
    result = parse_salary("8 to 12 lakhs per annum")
    assert result.salary_min == 800_000
    assert result.salary_max == 1_200_000
    assert result.salary_period == "annual"
    assert result.has_salary is True


def test_lpa_single_value():
    result = parse_salary("6 LPA")
    assert result.salary_min == 600_000
    assert result.salary_max == 600_000
    assert result.salary_period == "annual"
    assert result.has_salary is True


def test_k_per_month():
    result = parse_salary("50k/month")
    assert result.salary_min == 50_000
    assert result.salary_max == 50_000
    assert result.salary_period == "monthly"
    assert result.has_salary is True


def test_monthly_range_with_commas():
    result = parse_salary("40,000 - 60,000 per month")
    assert result.salary_min == 40_000
    assert result.salary_max == 60_000
    assert result.salary_period == "monthly"
    assert result.has_salary is True


def test_monthly_range_with_k_suffix_on_both_sides():
    result = parse_salary("40k-60k per month")
    assert result.salary_min == 40_000
    assert result.salary_max == 60_000
    assert result.salary_period == "monthly"


def test_hourly_single():
    result = parse_salary("500 per hour")
    assert result.salary_min == 500
    assert result.salary_max == 500
    assert result.salary_period == "hourly"
    assert result.has_salary is True


def test_hourly_shorthand():
    result = parse_salary("₹300-500/hr")
    assert result.salary_min == 300
    assert result.salary_max == 500
    assert result.salary_period == "hourly"


def test_annual_range_without_lpa_marker():
    result = parse_salary("800000-1200000 per annum")
    assert result.salary_min == 800_000
    assert result.salary_max == 1_200_000
    assert result.salary_period == "annual"


@pytest.mark.parametrize(
    "phrase",
    ["Not disclosed", "not disclosed by recruiter", "Negotiable", "NEGOTIABLE", "Confidential"],
)
def test_placeholder_phrases_are_treated_as_no_salary(phrase):
    result = parse_salary(phrase)
    assert result.has_salary is False
    assert result.salary_min is None
    assert result.salary_max is None
    assert result.salary_period is None


def test_no_salary_field_present_returns_none_input():
    """The canonical 'source has no salary field at all' case: caller
    passes None rather than an empty string.
    """
    result = parse_salary(None)
    assert result.has_salary is False
    assert result.salary_min is None
    assert result.salary_max is None
    assert result.salary_period is None


def test_empty_string_is_no_salary():
    result = parse_salary("")
    assert result.has_salary is False


def test_whitespace_only_is_no_salary():
    result = parse_salary("   ")
    assert result.has_salary is False


def test_unparseable_garbage_is_no_salary():
    result = parse_salary("competitive package with great perks")
    assert result.has_salary is False
    assert result.salary_min is None
    assert result.salary_max is None
