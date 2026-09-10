import Link from "next/link";
import { ArrowLeft, SearchX } from "lucide-react";

export default function NotFound() {
  return (
    <section className="mx-auto grid min-h-[28rem] max-w-2xl place-items-center px-4 py-12 text-center">
      <div>
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-clay-100 text-semantic-primary">
          <SearchX className="h-5 w-5" aria-hidden="true" />
        </span>
        <p className="mt-4 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-ink-400">404 · Not found</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink-700">This view is not available</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-500">
          The address may be outdated, or the resource may no longer be visible to your account.
        </p>
        <Link
          href="/"
          className="relative mt-5 inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-transparent bg-ink-700 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-ink-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Return to dashboard
        </Link>
      </div>
    </section>
  );
}
