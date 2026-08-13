/**
 * Job detail page — the page a candidate actually reads before applying,
 * and the one that matters most for search indexing.
 *
 * Server-rendered (like the listing) and additionally emits JobPosting
 * JSON-LD so Google can surface these in Google Jobs results.
 */
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import Badge from "@/components/Badge";
import JobCard from "@/components/JobCard";
import { ApiError, fetchJob, fetchJobs } from "@/lib/api";
import {
  companyInitial,
  experienceLabel,
  formatDate,
  formatSalary,
  looksLikeHeading,
  SITE_NAME,
  timeAgo,
  titleCase,
  toParagraphs,
} from "@/lib/format";
import type { Job } from "@/lib/types";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  let job: Job | null = null;
  try {
    job = await fetchJob(id);
  } catch {
    // Backend down at metadata time — fall through to generic metadata
    // rather than failing the whole render.
  }
  if (!job) return { title: "Job not found" };

  const where = job.is_remote ? "Remote" : (job.location ?? "India");
  return {
    title: `${job.title} at ${job.company} — ${where}`,
    description:
      job.description?.slice(0, 155) ??
      `${job.title} opening at ${job.company}${job.location ? ` in ${job.location}` : ""}.`,
  };
}

export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let job: Job | null;
  try {
    job = await fetchJob(id);
  } catch (err) {
    if (err instanceof ApiError) {
      return (
        <div className="mx-auto max-w-3xl px-4 py-16 text-center">
          <h1 className="text-xl font-semibold text-red-900 dark:text-red-200">
            Could not load this job
          </h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            {err.message}
          </p>
        </div>
      );
    }
    throw err;
  }

  if (!job) notFound();

  const salary = formatSalary(job);
  const experience = experienceLabel(job.seniority);
  const posted = formatDate(job.posted_at) ?? formatDate(job.scraped_at);
  const postedAgo = timeAgo(job.posted_at ?? job.scraped_at);
  const paragraphs = job.description ? toParagraphs(job.description) : [];

  const similar = await fetchSimilarJobs(job);

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:py-10">
      <JobPostingJsonLd job={job} />

      <nav className="mb-6 text-sm text-slate-500 dark:text-slate-400">
        <Link href="/" className="hover:text-blue-700 dark:hover:text-blue-400">
          All jobs
        </Link>
        <span className="mx-2" aria-hidden>
          /
        </span>
        <span className="text-slate-700 dark:text-slate-300">{job.title}</span>
      </nav>

      <article className="rounded-xl border border-slate-200 bg-white p-6 sm:p-8 dark:border-slate-700 dark:bg-slate-800">
        <header>
          {posted && (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Posted {posted}
              {postedAgo ? ` · ${postedAgo}` : ""}
            </p>
          )}

          <div className="mt-4 flex gap-4">
            <div
              aria-hidden
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-2xl font-semibold text-white"
            >
              {companyInitial(job.company)}
            </div>
            <div className="min-w-0">
              <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-100">
                {job.title}
              </h1>
              <p className="mt-1 text-base text-slate-600 dark:text-slate-400">
                at{" "}
                <span className="font-semibold text-slate-900 dark:text-slate-200">
                  {job.company}
                </span>
              </p>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            {job.employment_type && (
              <Badge variant="type">{titleCase(job.employment_type)}</Badge>
            )}
            {salary && <Badge variant="salary">{salary}</Badge>}
            {experience && <Badge variant="experience">{experience}</Badge>}
            {job.is_remote && <Badge variant="remote">Remote</Badge>}
            {job.location && <Badge>{job.location}</Badge>}
          </div>

          <ApplyButton job={job} className="mt-6 w-full sm:w-auto" />
        </header>

        {paragraphs.length > 0 ? (
          <section className="mt-8 border-t border-slate-200 pt-8 dark:border-slate-700">
            <h2 className="sr-only">Job description</h2>
            <div className="space-y-3">
              {paragraphs.map((line, index) =>
                looksLikeHeading(line) ? (
                  <h3
                    key={index}
                    className="pt-3 text-base font-semibold text-slate-900 dark:text-slate-100"
                  >
                    {line}
                  </h3>
                ) : (
                  <p
                    key={index}
                    className="text-[15px] leading-relaxed text-slate-700 dark:text-slate-300"
                  >
                    {line}
                  </p>
                ),
              )}
            </div>

            {!job.description_is_ai_rewritten && (
              <p className="mt-6 rounded-lg bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-700/50 dark:text-slate-300">
                This description is shown as published by the employer or source
                site.
              </p>
            )}
          </section>
        ) : (
          <section className="mt-8 border-t border-slate-200 pt-8 dark:border-slate-700">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No description was available for this listing. Use the apply link
              to read the full details on the company&apos;s site.
            </p>
          </section>
        )}

        {job.tags.length > 0 && (
          <section className="mt-8 border-t border-slate-200 pt-6 dark:border-slate-700">
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Skills to bring
            </h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {job.tags.map((tag) => (
                <Link key={tag} href={`/?tag=${encodeURIComponent(tag)}`}>
                  <Badge>{tag}</Badge>
                </Link>
              ))}
            </div>
          </section>
        )}

        <section className="mt-8 border-t border-slate-200 pt-6 dark:border-slate-700">
          <ApplyButton job={job} className="w-full sm:w-auto" />
          <p className="mt-4 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
            {SITE_NAME} is an independent platform listing openings gathered from
            public sources. We are not affiliated with {job.company} and do not
            handle applications. Never pay a fee to apply for a job.
          </p>
        </section>
      </article>

      {similar.length > 0 && (
        <section className="mt-10">
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
              Similar jobs
            </h2>
            <Link
              href="/"
              className="text-sm font-medium text-blue-700 hover:underline dark:text-blue-400"
            >
              Browse all
            </Link>
          </div>
          <div className="space-y-3">
            {similar.map((similarJob) => (
              <JobCard key={similarJob.id} job={similarJob} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function ApplyButton({ job, className = "" }: { job: Job; className?: string }) {
  return (
    <a
      href={job.apply_url}
      target="_blank"
      // noopener/noreferrer: apply_url points at third-party ATS domains.
      rel="noopener noreferrer nofollow"
      className={`inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 focus:ring-2 focus:ring-blue-300 focus:outline-none ${className}`}
    >
      Apply Now
      <span aria-hidden>→</span>
    </a>
  );
}

/**
 * "More like this": same primary skill tag when the job has one, else
 * same seniority. Over-fetches slightly then filters the current job out,
 * since the API has no "exclude id" parameter.
 */
async function fetchSimilarJobs(job: Job): Promise<Job[]> {
  const query = job.tags[0]
    ? { tag: job.tags[0], limit: 5 }
    : { seniority: job.seniority ?? undefined, limit: 5 };
  try {
    const { items } = await fetchJobs(query);
    return items.filter((item) => item.id !== job.id).slice(0, 4);
  } catch {
    // Similar jobs are a nice-to-have; never fail the page over them.
    return [];
  }
}

/**
 * Google Jobs structured data. Emitted as a JSON-LD script tag — the
 * stringified payload has `<` escaped so a description containing
 * "</script>" can't break out of the tag.
 */
function JobPostingJsonLd({ job }: { job: Job }) {
  const payload: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    description: job.description ?? job.title,
    datePosted: job.posted_at ?? job.scraped_at,
    employmentType: job.employment_type?.toUpperCase().replace("-", "_"),
    hiringOrganization: {
      "@type": "Organization",
      name: job.company,
    },
    directApply: false,
  };

  if (job.location) {
    payload.jobLocation = {
      "@type": "Place",
      address: {
        "@type": "PostalAddress",
        addressLocality: job.location,
        addressCountry: "IN",
      },
    };
  }

  if (job.is_remote) {
    payload.jobLocationType = "TELECOMMUTE";
  }

  if (job.has_salary && (job.salary_min || job.salary_max)) {
    payload.baseSalary = {
      "@type": "MonetaryAmount",
      currency: job.salary_currency,
      value: {
        "@type": "QuantitativeValue",
        minValue: job.salary_min ?? undefined,
        maxValue: job.salary_max ?? undefined,
        unitText: job.salary_period === "annual" ? "YEAR" : undefined,
      },
    };
  }

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(payload).replace(/</g, "\\u003c"),
      }}
    />
  );
}
