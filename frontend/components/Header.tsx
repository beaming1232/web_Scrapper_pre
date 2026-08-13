import Link from "next/link";

import ThemeToggle from "@/components/ThemeToggle";
import { SITE_NAME } from "@/lib/format";

const NAV_LINKS = [
  { label: "Remote", href: "/?is_remote=true" },
  { label: "Fresher", href: "/?seniority=fresher" },
  { label: "Internships", href: "/?employment_type=internship" },
];

export default function Header() {
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-700 dark:bg-slate-800/90">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3.5">
        <Link href="/" className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white"
          >
            F
          </span>
          <span className="text-lg font-bold tracking-tight text-slate-900 dark:text-slate-50">
            {SITE_NAME}
          </span>
        </Link>

        <nav className="flex items-center gap-1 text-sm font-medium sm:gap-2">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.label}
              href={link.href}
              className="rounded-lg px-3 py-1.5 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white"
            >
              {link.label}
            </Link>
          ))}
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
