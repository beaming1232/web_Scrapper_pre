/**
 * Listing page. A server component: it fetches from the FastAPI layer on
 * the server and ships rendered HTML, so job listings are indexable.
 *
 * All filter/sort/page state lives in the URL (searchParams), which is
 * what makes every filtered view shareable and crawlable — there is no
 * client-side state here at all.
 */
import JobCard from "@/components/JobCard";
import Pagination from "@/components/Pagination";
import SearchFilters from "@/components/SearchFilters";
import { ApiError, fetchJobs } from "@/lib/api";
import { SITE_NAME } from "@/lib/format";
import type { JobQuery } from "@/lib/types";

const PAGE_SIZE = 20;

type SearchParams = Record<string, string | string[] | undefined>;

/** searchParams values can be string | string[]; we only ever want one. */
function one(value: string | string[] | undefined): string | undefined {
  const single = Array.isArray(value) ? value[0] : value;
  return single && single.trim() !== "" ? single : undefined;
}

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;

  const q = one(params.q);
  const location = one(params.location);
  const employmentType = one(params.employment_type);
  const seniority = one(params.seniority);
  const source = one(params.source);
  const tag = one(params.tag);
  const isRemote = one(params.is_remote) === "true" ? true : undefined;
  const hasSalary = one(params.has_salary) === "true" ? true : undefined;
  const sort = one(params.sort) === "scraped_at" ? "scraped_at" : "posted_at";
  const offset = Math.max(0, Number(one(params.offset) ?? 0) || 0);

  const query: JobQuery = {
    q,
    location,
    employment_type: employmentType,
    seniority,
    source,
    tag,
    is_remote: isRemote,
    has_salary: hasSalary,
    sort,
    order: "desc",
    limit: PAGE_SIZE,
    offset,
  };

  let data;
  let error: string | null = null;
  try {
    data = await fetchJobs(query);
  } catch (err) {
    error =
      err instanceof ApiError
        ? err.message
        : "Something went wrong loading jobs.";
  }

  // Flattened copy for building pagination links that preserve filters.
  const flatParams: Record<string, string | undefined> = {
    q,
    location,
    employment_type: employmentType,
    seniority,
    source,
    tag,
    is_remote: isRemote ? "true" : undefined,
    has_salary: hasSalary ? "true" : undefined,
    sort,
  };

  const hasFilters = Boolean(
    q || location || employmentType || seniority || source || tag || isRemote || hasSalary,
  );

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:py-12">
      <section className="mb-8 text-center sm:mb-10">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl dark:text-slate-100">
          Start your tech career in India
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-base text-slate-600 dark:text-slate-400">
          Internships, fresher roles and graduate trainee openings from company
          career pages — updated daily, no login needed.
        </p>
      </section>

      <SearchFilters
        values={{
          q,
          location,
          employment_type: employmentType,
          seniority,
          source,
          is_remote: isRemote,
          has_salary: hasSalary,
          sort,
        }}
      />

      {error ? (
        <ErrorState message={error} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState hasFilters={hasFilters} />
      ) : (
        <>
          <p className="mt-8 mb-4 text-sm text-slate-600 dark:text-slate-400">
            <span className="font-semibold text-slate-900 dark:text-slate-100">
              {data.total}
            </span>{" "}
            {data.total === 1 ? "job" : "jobs"} found
            {hasFilters ? " for your filters" : ""}
          </p>

          <div className="space-y-3">
            {data.items.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>

          <Pagination
            total={data.total}
            limit={data.limit}
            offset={data.offset}
            searchParams={flatParams}
          />
        </>
      )}
    </div>
  );
}

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <div className="mt-8 rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center dark:border-slate-700 dark:bg-slate-800">
      <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
        No jobs found
      </p>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600 dark:text-slate-400">
        {hasFilters
          ? "Try removing a filter or searching for a broader job title."
          : `No job listings are stored yet. Run the scraper (python -m jobs.scrape_all) to populate ${SITE_NAME}.`}
      </p>
      {hasFilters && (
        <a
          href="/"
          className="mt-5 inline-block rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700"
        >
          Clear all filters
        </a>
      )}
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="mt-8 rounded-xl border border-red-200 bg-red-50 p-8 text-center dark:border-red-900 dark:bg-red-950/40">
      <p className="text-lg font-semibold text-red-900 dark:text-red-200">
        Could not load jobs
      </p>
      <p className="mt-2 text-sm text-red-800 dark:text-red-300">{message}</p>
      <p className="mt-4 text-xs text-red-700 dark:text-red-400">
        Start the backend with:{" "}
        <code className="rounded bg-red-100 px-1.5 py-0.5 font-mono dark:bg-red-900/50">
          uvicorn api.main:app --reload --port 8000
        </code>
      </p>
    </div>
  );
}
