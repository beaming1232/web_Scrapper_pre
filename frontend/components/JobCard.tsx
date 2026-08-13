import Link from "next/link";

import Badge from "./Badge";
import {
  companyInitial,
  experienceLabel,
  formatSalary,
  timeAgo,
  titleCase,
} from "@/lib/format";
import type { Job } from "@/lib/types";

/**
 * One job in a listing. The whole card is a single link to the detail
 * page — no nested "Apply" link here on purpose: applying should happen
 * from the detail page, after the candidate has read the description.
 */
export default function JobCard({ job }: { job: Job }) {
  const salary = formatSalary(job);
  const experience = experienceLabel(job.seniority);
  const posted = timeAgo(job.posted_at ?? job.scraped_at);

  return (
    <Link
      href={`/jobs/${job.id}`}
      className="group block rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-400 hover:shadow-md sm:p-5 dark:border-slate-700 dark:bg-slate-800 dark:hover:border-blue-600"
    >
      <div className="flex gap-4">
        <div
          aria-hidden
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-lg font-semibold text-white"
        >
          {companyInitial(job.company)}
        </div>

        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold text-slate-900 group-hover:text-blue-700 sm:text-lg dark:text-slate-50 dark:group-hover:text-blue-400">
            {job.title}
          </h2>

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-600 dark:text-slate-400">
            <span className="font-medium text-slate-800 dark:text-slate-200">
              {job.company}
            </span>
            {job.location && (
              <>
                <span aria-hidden>·</span>
                <span className="truncate">{job.location}</span>
              </>
            )}
            {posted && (
              <>
                <span aria-hidden>·</span>
                <span>{posted}</span>
              </>
            )}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {job.employment_type && (
              <Badge variant="type">{titleCase(job.employment_type)}</Badge>
            )}
            {salary && <Badge variant="salary">{salary}</Badge>}
            {experience && <Badge variant="experience">{experience}</Badge>}
            {job.is_remote && <Badge variant="remote">Remote</Badge>}
            {job.tags.slice(0, 3).map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
          </div>
        </div>
      </div>
    </Link>
  );
}
