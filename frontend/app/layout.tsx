import type { Metadata } from "next";
import { Inter } from "next/font/google";

import Footer from "@/components/Footer";
import Header from "@/components/Header";
import { SITE_NAME, SITE_TAGLINE } from "@/lib/format";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: {
    default: `${SITE_NAME} — ${SITE_TAGLINE}`,
    template: `%s | ${SITE_NAME}`,
  },
  description:
    "Find entry-level software and IT jobs across India — internships, fresher roles and graduate trainee openings, gathered from company career pages and job boards.",
};

/**
 * Applies the saved theme before the browser paints anything.
 *
 * This has to be a blocking inline script in <head>: if the `.dark` class
 * were added later (in an effect, after hydration), a visitor who chose
 * dark would get a bright white flash on every single page load. Reading
 * localStorage synchronously here is the standard way to avoid that.
 *
 * Light is the default — dark applies only when explicitly chosen. The OS
 * `prefers-color-scheme` setting is intentionally not consulted, so a
 * first-time visitor always lands on the light theme.
 */
const THEME_INIT_SCRIPT = `
try {
  if (localStorage.getItem('theme') === 'dark') {
    document.documentElement.classList.add('dark');
  }
} catch (e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: the script above mutates <html>'s class
    // list before React hydrates, so server and client markup differ here
    // by design. Scoped to this element only.
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body
        className={`${inter.variable} flex min-h-screen flex-col bg-slate-50 font-sans text-slate-900 antialiased dark:bg-slate-900 dark:text-slate-100`}
      >
        <Header />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
