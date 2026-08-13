import Link from "next/link";

import { SITE_NAME, SITE_TAGLINE } from "@/lib/format";

const JOB_TYPES = [
  { label: "Internships", href: "/?employment_type=internship" },
  { label: "Full-time jobs", href: "/?employment_type=full-time" },
  { label: "Remote jobs", href: "/?is_remote=true" },
  { label: "Fresher jobs", href: "/?seniority=fresher" },
  { label: "Jobs with salary listed", href: "/?has_salary=true" },
];

const LOCATIONS = [
  "Bangalore",
  "Hyderabad",
  "Pune",
  "Chennai",
  "Mumbai",
  "Noida",
  "Gurgaon",
];

const ROLES = [
  "Software Engineer",
  "Frontend",
  "Backend",
  "Full Stack",
  "Data",
  "DevOps",
  "QA",
];

export default function Footer() {
  return (
    <footer className="mt-16 border-t border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
      <div className="mx-auto max-w-5xl px-4 py-12">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="lg:col-span-1">
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white"
              >
                F
              </span>
              <span className="text-base font-bold text-slate-900 dark:text-slate-100">
                {SITE_NAME}
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
              {SITE_TAGLINE} We gather openings from job boards and company
              career pages so you spend less time searching and more time
              applying.
            </p>
          </div>

          <FooterColumn title="Browse by type">
            {JOB_TYPES.map((item) => (
              <FooterLink key={item.label} href={item.href}>
                {item.label}
              </FooterLink>
            ))}
          </FooterColumn>

          <FooterColumn title="Jobs by city">
            {LOCATIONS.map((city) => (
              <FooterLink
                key={city}
                href={`/?location=${encodeURIComponent(city)}`}
              >
                Jobs in {city}
              </FooterLink>
            ))}
          </FooterColumn>

          <FooterColumn title="Jobs by role">
            {ROLES.map((role) => (
              <FooterLink key={role} href={`/?q=${encodeURIComponent(role)}`}>
                {role} jobs
              </FooterLink>
            ))}
          </FooterColumn>
        </div>

        <div className="mt-10 border-t border-slate-200 pt-6 dark:border-slate-700">
          <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">
            {SITE_NAME} is an independent platform that lists job openings
            gathered from public sources. We are not affiliated with, and do not
            represent, any company or recruiter named in a listing. Always apply
            through the official link and never pay a fee to apply for a job.
          </p>
          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            © {new Date().getFullYear()} {SITE_NAME}. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}

function FooterColumn({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
        {title}
      </h3>
      <ul className="mt-3 space-y-2">{children}</ul>
    </div>
  );
}

function FooterLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <li>
      <Link
        href={href}
        className="text-sm text-slate-600 transition hover:text-blue-700 dark:text-slate-400 dark:hover:text-blue-400"
      >
        {children}
      </Link>
    </li>
  );
}
