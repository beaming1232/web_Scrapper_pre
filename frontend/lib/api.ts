/**
 * Server-side client for the FastAPI read layer (`api/` in the repo root).
 *
 * These run in React Server Components, so the browser never talks to the
 * API (or Postgres) directly — pages arrive as fully-rendered HTML. That's
 * deliberate: job listings need to be indexable by search engines, which a
 * client-side-fetched list would not be.
 *
 * `cache: "no-store"` because the underlying table changes whenever
 * `python -m jobs.scrape_all` runs; a stale cached page would show jobs
 * that have since been deactivated by jobs/health_check.py.
 */
import type { Job, JobList, JobQuery, SocialDigest } from "./types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

function buildQuery(query: JobQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** Thrown when the API is unreachable or returns a non-2xx status. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function fetchJobs(query: JobQuery = {}): Promise<JobList> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/jobs${buildQuery(query)}`, {
      cache: "no-store",
    });
  } catch {
    // Most commonly: the FastAPI server isn't running. Surfaced to the
    // page as an explicit "backend unreachable" state rather than an
    // empty job list, so it isn't mistaken for "no jobs matched".
    throw new ApiError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (!response.ok) {
    throw new ApiError(`API returned ${response.status}.`, response.status);
  }
  return response.json();
}

/** The ready-to-post social message for jobs stored in the last `hours`. */
export async function fetchSocialDigest(hours?: number): Promise<SocialDigest> {
  const qs = hours === undefined ? "" : `?hours=${hours}`;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/social/digest${qs}`, {
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (!response.ok) {
    throw new ApiError(`API returned ${response.status}.`, response.status);
  }
  return response.json();
}

/** Returns null when the job doesn't exist (API 404), so callers can
 *  render a not-found page instead of treating it as a hard failure. */
export async function fetchJob(id: string): Promise<Job | null> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/jobs/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`Could not reach the API at ${API_BASE_URL}.`);
  }
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new ApiError(`API returned ${response.status}.`, response.status);
  }
  return response.json();
}
