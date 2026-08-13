/** Display formatting helpers. Pure functions, no React. */
import type { Job } from "./types";

/** Public-facing site name. Single source of truth — change it here. */
export const SITE_NAME = "FresherJobs";
export const SITE_TAGLINE = "Entry-level tech jobs across India, in one place.";

/**
 * Formats salary the way Indian job boards conventionally do: annual INR
 * as "LPA" (lakhs per annum), e.g. 600000–1200000 -> "6-12 LPA".
 *
 * Falls back to the source's own `salary_raw` string for anything that
 * isn't annual INR (other currencies, monthly/hourly rates) rather than
 * mislabelling it — scrapers record plenty of non-annual values.
 */
export function formatSalary(job: Job): string | null {
  if (!job.has_salary) return null;

  const isAnnualInr =
    job.salary_currency === "INR" &&
    (job.salary_period === "annual" || job.salary_period === null);

  if (isAnnualInr && (job.salary_min || job.salary_max)) {
    const toLpa = (n: number) => {
      const lpa = n / 100_000;
      // Avoid "7.0 LPA" while keeping "7.5 LPA" intact.
      return Number.isInteger(lpa) ? String(lpa) : lpa.toFixed(1);
    };
    if (job.salary_min && job.salary_max) {
      return `${toLpa(job.salary_min)}-${toLpa(job.salary_max)} LPA`;
    }
    const single = job.salary_min ?? job.salary_max;
    return single ? `${toLpa(single)} LPA` : null;
  }

  return job.salary_raw;
}

/** "2 hours ago" / "3 days ago" — the freshness cue a job board lives on. */
export function timeAgo(iso: string | null): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;

  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 60) return "just now";

  const units: [number, string][] = [
    [60, "minute"],
    [60, "hour"],
    [24, "day"],
    [30, "month"],
  ];

  let value = seconds;
  let label = "second";
  for (const [divisor, nextLabel] of units) {
    if (value < divisor) break;
    value = Math.floor(value / divisor);
    label = nextLabel;
  }
  return `${value} ${label}${value === 1 ? "" : "s"} ago`;
}

export function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** "full-time" -> "Full-time", "fresher" -> "Fresher". */
export function titleCase(value: string | null): string | null {
  if (!value) return null;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** Experience hint derived from seniority, mirroring how Indian boards
 *  label entry-level roles ("Fresher", "1-3 yrs"). */
export function experienceLabel(seniority: string | null): string | null {
  if (!seniority) return null;
  const map: Record<string, string> = {
    fresher: "Fresher",
    junior: "1-3 yrs",
    mid: "3-6 yrs",
    senior: "6+ yrs",
    lead: "Lead",
  };
  return map[seniority] ?? titleCase(seniority);
}

/** First letter of the company, for the avatar tile on each card. */
export function companyInitial(company: string): string {
  return company.trim().charAt(0).toUpperCase() || "?";
}

/**
 * Splits a plain-text description into paragraphs for rendering.
 *
 * Descriptions are always plain text, never HTML — both the AI rewriter
 * (pipeline/rewriter.py forbids markdown in its system prompt) and the
 * scrapers' own HTML-stripping guarantee that. So this renders as text
 * nodes; nothing here injects HTML.
 */
export function toParagraphs(description: string): string[] {
  return description
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Heuristic: a short line with no sentence-ending punctuation is almost
 *  always a section heading ("Qualifications", "Role Description:"). Used
 *  only to style such lines more prominently — the text is unchanged
 *  either way, so a wrong guess is cosmetic, never lossy. */
export function looksLikeHeading(line: string): boolean {
  return line.length <= 60 && !/[.!?]$/.test(line) && !line.startsWith("•");
}
