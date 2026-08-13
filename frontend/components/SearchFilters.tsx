/**
 * Filter bar for the listing page.
 *
 * A plain GET <form> pointing at "/" — field names are exactly the API's
 * query parameter names, so submitting produces a shareable, bookmarkable
 * URL (/?q=react&location=Pune) that the server component reads straight
 * back out of searchParams. No client-side state, no "use client", and it
 * works with JavaScript disabled.
 *
 * `offset` is deliberately not a field here: changing a filter should
 * always land you back on page 1, which happens naturally because the
 * submitted URL omits offset entirely.
 */
const EMPLOYMENT_TYPES = [
  { value: "", label: "Any type" },
  { value: "full-time", label: "Full-time" },
  { value: "internship", label: "Internship" },
  { value: "part-time", label: "Part-time" },
  { value: "contract", label: "Contract" },
];

const SENIORITIES = [
  { value: "", label: "Any experience" },
  { value: "fresher", label: "Fresher" },
  { value: "junior", label: "1-3 yrs" },
  { value: "mid", label: "3-6 yrs" },
  { value: "senior", label: "6+ yrs" },
];

const SORTS = [
  { value: "posted_at", label: "Newest posted" },
  { value: "scraped_at", label: "Recently added" },
];

// Hand-listed rather than fetched from the registry: the two sources that
// exist today (scrapers/sources/jobfound.py, scrapers/sources/talentd.py).
// A future new source needs a line added here to appear as a filter
// option — everything else about adding a source is zero-config, but this
// one label list isn't, same tradeoff as EMPLOYMENT_TYPES/SENIORITIES above.
const SOURCES = [
  { value: "", label: "All sources" },
  { value: "jobfound", label: "Jobfound" },
  { value: "talentd", label: "Talentd" },
];

// Inputs sit *recessed* against the card in dark mode (slate-900 field on
// an slate-800 card) — matching the card colour would make the field
// boundaries disappear entirely.
const FIELD_CLASSES =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-blue-900";

export interface FilterValues {
  q?: string;
  location?: string;
  employment_type?: string;
  seniority?: string;
  source?: string;
  is_remote?: boolean;
  has_salary?: boolean;
  sort?: string;
}

export default function SearchFilters({ values }: { values: FilterValues }) {
  return (
    <form
      action="/"
      method="get"
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-slate-700 dark:text-slate-300">
            Job title or company
          </span>
          <input
            type="search"
            name="q"
            defaultValue={values.q ?? ""}
            placeholder="e.g. Software Engineer, Infosys"
            className={FIELD_CLASSES}
          />
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-slate-700 dark:text-slate-300">
            Location
          </span>
          <input
            type="search"
            name="location"
            defaultValue={values.location ?? ""}
            placeholder="e.g. Bangalore"
            className={FIELD_CLASSES}
          />
        </label>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Select
          name="employment_type"
          label="Job type"
          options={EMPLOYMENT_TYPES}
          value={values.employment_type}
        />
        <Select
          name="seniority"
          label="Experience"
          options={SENIORITIES}
          value={values.seniority}
        />
        <Select name="source" label="Source" options={SOURCES} value={values.source} />
        <Select
          name="sort"
          label="Sort by"
          options={SORTS}
          value={values.sort ?? "posted_at"}
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-4">
          <Checkbox name="is_remote" label="Remote only" checked={values.is_remote} />
          <Checkbox
            name="has_salary"
            label="Salary listed"
            checked={values.has_salary}
          />
        </div>

        <div className="flex gap-2">
          <a
            href="/"
            className="rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Clear
          </a>
          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 focus:ring-2 focus:ring-blue-300 focus:outline-none"
          >
            Search
          </button>
        </div>
      </div>
    </form>
  );
}

function Select({
  name,
  label,
  options,
  value,
}: {
  name: string;
  label: string;
  options: { value: string; label: string }[];
  value?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-700 dark:text-slate-300">
        {label}
      </span>
      <select name={name} defaultValue={value ?? ""} className={FIELD_CLASSES}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Checkbox({
  name,
  label,
  checked,
}: {
  name: string;
  label: string;
  checked?: boolean;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
      <input
        type="checkbox"
        name={name}
        value="true"
        defaultChecked={checked}
        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-900"
      />
      {label}
    </label>
  );
}
