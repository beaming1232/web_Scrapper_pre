"""
Salary parsing for Indian job listings.

Turns whatever free-form salary string a source provides into
(salary_min, salary_max, salary_period) in whole-rupee (or other currency)
units. Never raises — a string it can't confidently parse is treated the
same as "no salary": everything comes back None/False.

Supported input shapes (see tests/test_salary_parser.py for the full
matrix):
    "₹8-12 LPA"                  -> 800000 - 1200000, annual
    "8 to 12 lakhs per annum"    -> 800000 - 1200000, annual
    "8-12 LPA"                   -> 800000 - 1200000, annual
    "6 LPA"                      -> 600000 - 600000, annual
    "50k/month"                  -> 50000 - 50000, monthly
    "40,000 - 60,000 per month"  -> 40000 - 60000, monthly
    "500 per hour" / "500/hr"    -> 500 - 500, hourly
    "Not disclosed" / "Negotiable" / "" / None -> no salary (has_salary=False)

Explicitly NOT in scope: currencies other than INR (they pass through
unparsed -> no salary), and salary text embedded inside a full JD
paragraph (callers should pass the dedicated salary field/snippet, not
the whole description).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSalary:
    salary_min: int | None
    salary_max: int | None
    salary_period: str | None  # "annual" | "monthly" | "hourly" | None
    has_salary: bool


_NO_SALARY_PHRASES = {
    "not disclosed",
    "not disclosed by recruiter",
    "negotiable",
    "n/a",
    "na",
    "as per industry standards",
    "as per company standards",
    "confidential",
    "unpaid",
    "-",
}

# Matches a number like "8", "8.5", "1,20,000", "120000"
_NUM = r"(\d[\d,]*(?:\.\d+)?)"

# LPA / lakh(s) per annum, with an optional range "8-12" or "8 to 12"
_LPA_RANGE_RE = re.compile(
    rf"{_NUM}\s*(?:-|to|–|—)\s*{_NUM}\s*(?:lpa|lakhs?(?:\s*per\s*annum)?|l\.?p\.?a\.?)",
    re.IGNORECASE,
)
_LPA_SINGLE_RE = re.compile(
    rf"{_NUM}\s*(?:lpa|lakhs?(?:\s*per\s*annum)?|l\.?p\.?a\.?)",
    re.IGNORECASE,
)

# "50k/month", "50k per month", "40,000 - 60,000 per month", "40000-60000/month"
_MONTHLY_RANGE_RE = re.compile(
    rf"{_NUM}\s*k?\s*(?:-|to|–|—)\s*{_NUM}\s*k?\s*"
    r"(?:/\s*month|per\s*month|/\s*mo\b|monthly)",
    re.IGNORECASE,
)
_MONTHLY_SINGLE_RE = re.compile(
    rf"{_NUM}\s*(k)?\s*(?:/\s*month|per\s*month|/\s*mo\b|monthly)",
    re.IGNORECASE,
)

# "500 per hour", "500/hr", "₹300-500/hour"
_HOURLY_RANGE_RE = re.compile(
    rf"{_NUM}\s*(?:-|to|–|—)\s*{_NUM}\s*"
    r"(?:/\s*hour|per\s*hour|/\s*hr\b|hourly)",
    re.IGNORECASE,
)
_HOURLY_SINGLE_RE = re.compile(
    rf"{_NUM}\s*(?:/\s*hour|per\s*hour|/\s*hr\b|hourly)",
    re.IGNORECASE,
)

# Bare annual range with no explicit LPA marker, e.g. "800000-1200000 per annum"
_ANNUAL_RANGE_RE = re.compile(
    rf"{_NUM}\s*(?:-|to|–|—)\s*{_NUM}\s*(?:per\s*annum|/\s*annum|p\.?a\.?|annually)",
    re.IGNORECASE,
)
_ANNUAL_SINGLE_RE = re.compile(
    rf"{_NUM}\s*(?:per\s*annum|/\s*annum|p\.?a\.?|annually)",
    re.IGNORECASE,
)


def _to_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _no_salary() -> ParsedSalary:
    return ParsedSalary(salary_min=None, salary_max=None, salary_period=None, has_salary=False)


def parse_salary(raw: str | None) -> ParsedSalary:
    """Parse a free-form salary string into structured min/max/period.

    Returns a ParsedSalary with has_salary=False for:
    - None or empty/whitespace-only input
    - "no salary field present" sentinel values (None IS that case)
    - phrases like "Not disclosed" / "Negotiable" (never stored as data)
    - strings that don't match any known pattern

    Never raises.
    """
    if raw is None:
        return _no_salary()

    text = raw.strip()
    if not text:
        return _no_salary()

    normalized = text.lower().strip()
    # Strip a leading currency symbol/word before checking no-salary phrases
    # and before matching, so "₹Negotiable" / "INR Not Disclosed" still hit.
    normalized = re.sub(r"^(₹|rs\.?|inr)\s*", "", normalized).strip()

    if normalized in _NO_SALARY_PHRASES:
        return _no_salary()

    # --- LPA / lakhs per annum ------------------------------------------
    m = _LPA_RANGE_RE.search(text)
    if m:
        lo, hi = _to_number(m.group(1)), _to_number(m.group(2))
        return ParsedSalary(
            salary_min=round(lo * 100_000),
            salary_max=round(hi * 100_000),
            salary_period="annual",
            has_salary=True,
        )
    m = _LPA_SINGLE_RE.search(text)
    if m:
        val = round(_to_number(m.group(1)) * 100_000)
        return ParsedSalary(salary_min=val, salary_max=val, salary_period="annual", has_salary=True)

    # --- explicit "per annum" bare numbers (no LPA marker) ----------------
    m = _ANNUAL_RANGE_RE.search(text)
    if m:
        lo, hi = round(_to_number(m.group(1))), round(_to_number(m.group(2)))
        return ParsedSalary(salary_min=lo, salary_max=hi, salary_period="annual", has_salary=True)
    m = _ANNUAL_SINGLE_RE.search(text)
    if m:
        val = round(_to_number(m.group(1)))
        return ParsedSalary(salary_min=val, salary_max=val, salary_period="annual", has_salary=True)

    # --- monthly ------------------------------------------------------------
    m = _MONTHLY_RANGE_RE.search(text)
    if m:
        lo_raw, hi_raw = m.group(1), m.group(2)
        lo = _to_number(lo_raw)
        hi = _to_number(hi_raw)
        # "k" suffix applies per-number if present right after that number;
        # detect via a lightweight re-scan of the matched span.
        span_text = text[m.start():m.end()]
        lo = _apply_k_suffix(span_text, lo_raw, lo)
        hi = _apply_k_suffix(span_text, hi_raw, hi)
        return ParsedSalary(
            salary_min=round(lo), salary_max=round(hi), salary_period="monthly", has_salary=True
        )
    m = _MONTHLY_SINGLE_RE.search(text)
    if m:
        val = _to_number(m.group(1))
        if m.group(2):  # the "k" group
            val *= 1000
        return ParsedSalary(
            salary_min=round(val), salary_max=round(val), salary_period="monthly", has_salary=True
        )

    # --- hourly -----------------------------------------------------------
    m = _HOURLY_RANGE_RE.search(text)
    if m:
        lo, hi = round(_to_number(m.group(1))), round(_to_number(m.group(2)))
        return ParsedSalary(salary_min=lo, salary_max=hi, salary_period="hourly", has_salary=True)
    m = _HOURLY_SINGLE_RE.search(text)
    if m:
        val = round(_to_number(m.group(1)))
        return ParsedSalary(salary_min=val, salary_max=val, salary_period="hourly", has_salary=True)

    # Nothing matched -> treat as no usable salary data, but the raw string
    # is still preserved upstream by the caller (salary_raw is set by the
    # scraper/normalize step, not by this function).
    return _no_salary()


def _apply_k_suffix(span_text: str, num_raw: str, value: float) -> float:
    """If `num_raw` inside `span_text` is immediately followed by an optional
    space and a 'k', multiply by 1000. Used for '40k-60k/month' style ranges
    where each side may or may not carry its own 'k'.
    """
    pattern = re.escape(num_raw) + r"\s*k\b"
    if re.search(pattern, span_text, re.IGNORECASE):
        return value * 1000
    return value
