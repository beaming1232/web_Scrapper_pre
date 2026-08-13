/**
 * Mirrors the backend's public response shapes (api/schemas.py).
 *
 * Deliberately matches `JobOut`, not the DB's `JobModel` — the backend
 * hides internal columns (fingerprint, resolved_domain, external_id) and
 * never sends `description_original` as its own field. `description`
 * below is the backend's derived value: the AI rewrite when one exists,
 * otherwise the raw scraped text as a fallback. `descriptionIsAiRewritten`
 * says which one you got — see api/schemas.py for why that distinction
 * is exposed rather than hidden.
 */
export interface Job {
  id: string;
  source: string;
  title: string;
  company: string;
  location: string | null;
  is_remote: boolean;

  employment_type: string | null;
  seniority: string | null;

  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  salary_period: string | null;
  salary_raw: string | null;
  has_salary: boolean;

  description: string | null;
  description_is_ai_rewritten: boolean;

  tags: string[];

  apply_type: string;
  apply_url: string;

  posted_at: string | null;
  scraped_at: string;

  merged_sources: string[];
}

export interface JobList {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

/** Query parameters accepted by GET /jobs. */
export interface JobQuery {
  source?: string;
  location?: string;
  employment_type?: string;
  seniority?: string;
  is_remote?: boolean;
  has_salary?: boolean;
  min_salary?: number;
  tag?: string;
  q?: string;
  sort?: "posted_at" | "scraped_at";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}
