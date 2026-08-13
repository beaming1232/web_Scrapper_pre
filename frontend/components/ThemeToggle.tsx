"use client";

/**
 * Light/dark toggle.
 *
 * The only client component in the app — it needs a click handler and
 * localStorage, neither of which exist on the server. Everything else
 * stays a server component (see frontend/lib/api.ts's docstring for why
 * that matters for SEO).
 *
 * Deliberately holds no React state. Which icon shows is decided purely
 * by CSS (`dark:` variants keyed off the `.dark` class on <html>), which
 * the inline script in app/layout.tsx has already applied before React
 * hydrates. Tracking the theme in useState instead would render the wrong
 * icon on the server — the server can't know the visitor's stored
 * preference — and produce a hydration mismatch plus a visible icon flip.
 */
export default function ThemeToggle() {
  function toggleTheme() {
    const root = document.documentElement;
    const nextIsDark = !root.classList.contains("dark");
    root.classList.toggle("dark", nextIsDark);
    try {
      localStorage.setItem("theme", nextIsDark ? "dark" : "light");
    } catch {
      // Private-browsing / storage-blocked: the toggle still works for
      // this page view, it just won't be remembered on the next one.
    }
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label="Toggle dark mode"
      title="Toggle dark mode"
      className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white"
    >
      {/* Moon: shown in light mode (click = go dark) */}
      <svg
        aria-hidden
        className="block h-[18px] w-[18px] dark:hidden"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>

      {/* Sun: shown in dark mode (click = go light) */}
      <svg
        aria-hidden
        className="hidden h-[18px] w-[18px] dark:block"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
      </svg>
    </button>
  );
}
