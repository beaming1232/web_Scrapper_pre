import Link from "next/link";

/**
 * Offset-based pager matching the API's limit/offset contract. Renders
 * real <a> links (not buttons) so pages are crawlable and the browser's
 * back button behaves — every page is its own URL.
 */
export default function Pagination({
  total,
  limit,
  offset,
  searchParams,
}: {
  total: number;
  limit: number;
  offset: number;
  searchParams: Record<string, string | undefined>;
}) {
  const totalPages = Math.ceil(total / limit);
  if (totalPages <= 1) return null;

  const currentPage = Math.floor(offset / limit) + 1;

  const hrefForPage = (page: number) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(searchParams)) {
      if (value && key !== "offset") params.set(key, value);
    }
    const pageOffset = (page - 1) * limit;
    if (pageOffset > 0) params.set("offset", String(pageOffset));
    const qs = params.toString();
    return qs ? `/?${qs}` : "/";
  };

  // Compact window of page numbers around the current page, so a large
  // result set doesn't render hundreds of links.
  const windowSize = 2;
  const pages: number[] = [];
  for (
    let page = Math.max(1, currentPage - windowSize);
    page <= Math.min(totalPages, currentPage + windowSize);
    page += 1
  ) {
    pages.push(page);
  }

  const baseClasses =
    "inline-flex h-9 min-w-9 items-center justify-center rounded-lg px-3 text-sm font-medium transition";
  const inactiveClasses =
    "border border-slate-300 bg-white text-slate-700 hover:border-blue-400 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-blue-600";

  return (
    <nav
      aria-label="Pagination"
      className="mt-8 flex flex-wrap items-center justify-center gap-2"
    >
      {currentPage > 1 && (
        <Link
          href={hrefForPage(currentPage - 1)}
          className={`${baseClasses} ${inactiveClasses}`}
        >
          ← Previous
        </Link>
      )}

      {pages[0] > 1 && (
        <>
          <Link href={hrefForPage(1)} className={`${baseClasses} ${inactiveClasses}`}>
            1
          </Link>
          {pages[0] > 2 && (
            <span className="px-1 text-slate-400" aria-hidden>
              …
            </span>
          )}
        </>
      )}

      {pages.map((page) =>
        page === currentPage ? (
          <span
            key={page}
            aria-current="page"
            className={`${baseClasses} bg-blue-600 text-white`}
          >
            {page}
          </span>
        ) : (
          <Link
            key={page}
            href={hrefForPage(page)}
            className={`${baseClasses} ${inactiveClasses}`}
          >
            {page}
          </Link>
        ),
      )}

      {pages[pages.length - 1] < totalPages && (
        <>
          {pages[pages.length - 1] < totalPages - 1 && (
            <span className="px-1 text-slate-400" aria-hidden>
              …
            </span>
          )}
          <Link
            href={hrefForPage(totalPages)}
            className={`${baseClasses} ${inactiveClasses}`}
          >
            {totalPages}
          </Link>
        </>
      )}

      {currentPage < totalPages && (
        <Link
          href={hrefForPage(currentPage + 1)}
          className={`${baseClasses} ${inactiveClasses}`}
        >
          Next →
        </Link>
      )}
    </nav>
  );
}
