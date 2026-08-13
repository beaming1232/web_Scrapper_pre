import type { ReactNode } from "react";

/**
 * Colour is used as a scanning aid, not decoration: each variant marks a
 * different kind of fact about a job, so a candidate can pick salary or
 * job type out of a badge row at a glance. All tones are deliberately
 * low-saturation — on a listing page a card can show four badges at once,
 * and saturated chips turn that into noise.
 */
type Variant = "default" | "salary" | "remote" | "type" | "experience";

const VARIANT_CLASSES: Record<Variant, string> = {
  default:
    "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-700/60 dark:text-slate-200 dark:ring-slate-600",
  type: "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-950/50 dark:text-blue-300 dark:ring-blue-800/60",
  salary:
    "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:ring-emerald-800/60",
  remote:
    "bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-800/60",
  experience:
    "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:ring-amber-800/60",
};

export default function Badge({
  children,
  variant = "default",
}: {
  children: ReactNode;
  variant?: Variant;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${VARIANT_CLASSES[variant]}`}
    >
      {children}
    </span>
  );
}
