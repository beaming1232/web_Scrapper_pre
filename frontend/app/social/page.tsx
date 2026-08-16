/**
 * Social digest — the ready-to-post message for jobs stored recently.
 *
 * One message, posted verbatim to X, WhatsApp and Telegram. Not three
 * variants: X caps posts at 280 characters and bills every URL at 23, and the
 * three platforms disagree on bold syntax, so anything richer breaks somewhere.
 * See social/digest.py for the full reasoning.
 *
 * A server component like every other page here, and deliberately with no
 * `"use client"`: the repo's rule is that there is none anywhere, and a
 * one-click copy button would be the first. The message sits in a readonly
 * <textarea> instead — click it and the browser selects the whole thing, then
 * Ctrl+C. Same result, no client bundle, rule intact.
 *
 * `noindex` because this is an operator page, not content. It must never turn
 * up in search results next to the job listings.
 */
import { ApiError, fetchSocialDigest } from "@/lib/api";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Social digest",
  robots: { index: false, follow: false },
};

type SearchParams = Record<string, string | string[] | undefined>;

const PLATFORMS = [
  { name: "X / Twitter", note: "Paste as-is. 280-character limit applies." },
  { name: "WhatsApp Community", note: "Paste as-is. No length limit." },
  { name: "Telegram Channel", note: "Paste as-is. No length limit." },
];

export default async function SocialPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const raw = Array.isArray(params.hours) ? params.hours[0] : params.hours;
  const parsed = raw ? Number(raw) : undefined;
  const hours = parsed !== undefined && Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;

  let digest;
  try {
    digest = await fetchSocialDigest(hours);
  } catch (error) {
    const message =
      error instanceof ApiError ? error.message : "Something went wrong loading the digest.";
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-2xl font-semibold">Social digest</h1>
        <p className="mt-4 rounded-lg border border-red-300 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {message}
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-semibold">Social digest</h1>
      <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
        {digest.job_count} job{digest.job_count === 1 ? "" : "s"} stored in the last{" "}
        {digest.window_hours} hours.{" "}
        <a className="underline" href="/social?hours=6">
          6h
        </a>{" "}
        ·{" "}
        <a className="underline" href="/social?hours=24">
          24h
        </a>{" "}
        ·{" "}
        <a className="underline" href="/social?hours=72">
          72h
        </a>
      </p>

      {digest.message === null ? (
        <p className="mt-8 rounded-lg border border-neutral-300 bg-neutral-50 p-4 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300">
          No jobs stored in this window, so there is nothing worth posting. A quiet run is
          normal — try a longer window above.
        </p>
      ) : (
        <>
          <section className="mt-8">
            <div className="flex items-baseline justify-between gap-4">
              <h2 className="font-medium">The message</h2>
              <span
                className={
                  digest.fits_x_limit
                    ? "text-sm text-green-700 dark:text-green-400"
                    : "text-sm font-semibold text-red-700 dark:text-red-400"
                }
              >
                {digest.x_character_count}/280 for X
                {digest.fits_x_limit ? "" : " — too long!"}
              </span>
            </div>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Naming {digest.listed_count} of {digest.job_count}. Click the box, then Ctrl+A
              and Ctrl+C.
            </p>
            <textarea
              readOnly
              rows={12}
              value={digest.message}
              aria-label="Social post text"
              className="mt-3 w-full rounded-lg border border-neutral-300 bg-white p-4 font-mono text-sm leading-relaxed text-neutral-900 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100"
            />
          </section>

          <section className="mt-8">
            <h2 className="font-medium">Post it to</h2>
            <ul className="mt-3 space-y-2">
              {PLATFORMS.map((platform) => (
                <li
                  key={platform.name}
                  className="rounded-lg border border-neutral-300 p-3 dark:border-neutral-700"
                >
                  <span className="font-medium">{platform.name}</span>
                  <span className="ml-2 text-sm text-neutral-600 dark:text-neutral-400">
                    {platform.note}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-sm text-neutral-600 dark:text-neutral-400">
              Every link points at {digest.site_url} rather than the employer&apos;s apply
              page, so the click lands here and the reader applies from the job page.
            </p>
          </section>
        </>
      )}
    </main>
  );
}
