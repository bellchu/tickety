"use client";

import { useEffect } from "react";
import { dmMono, dmSans } from "./fonts";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Application shell failed", {
      name: error.name,
      digest: error.digest,
    });
  }, [error]);

  return (
    <html lang="en">
      <body className={`tickety-ui ${dmSans.variable} ${dmMono.variable}`}>
        <main className="tickety-ambient grid min-h-screen place-items-center p-6">
          <div className="w-full max-w-md rounded-2xl border border-linen-400 bg-white p-7 text-center shadow-[var(--shadow-raised)]">
            <div aria-hidden="true" className="tickety-accent mx-auto h-1 w-20 rounded-full" />
            <h1 className="mt-5 text-xl font-semibold text-ink-700">Tickety OPS Tower needs a fresh start</h1>
            <p className="mt-2 text-sm leading-6 text-ink-500">
              An unexpected application error interrupted this session. Retry without losing your saved service data.
            </p>
            <button
              type="button"
              onClick={reset}
              className="relative mt-5 inline-flex min-h-10 items-center justify-center rounded-md border border-transparent bg-ink-700 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-ink-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2"
            >
              Retry application
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
