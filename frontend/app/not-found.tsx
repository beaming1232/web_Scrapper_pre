import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-24 text-center">
      <p className="text-sm font-semibold text-blue-600 dark:text-blue-400">
        404
      </p>
      <h1 className="mt-2 text-2xl font-bold text-slate-900 sm:text-3xl dark:text-slate-100">
        This job is no longer listed
      </h1>
      <p className="mt-3 text-slate-600 dark:text-slate-400">
        It may have been filled or removed by the employer. Plenty of other
        openings are waiting.
      </p>
      <Link
        href="/"
        className="mt-8 inline-block rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-700"
      >
        Browse all jobs
      </Link>
    </div>
  );
}
