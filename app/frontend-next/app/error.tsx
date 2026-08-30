"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Route render failed", {
      name: error.name,
      digest: error.digest,
    });
  }, [error]);

  return (
    <section
      role="alert"
      className="mx-auto grid min-h-[28rem] max-w-2xl place-items-center px-4 py-12 text-center"
    >
      <div>
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[var(--color-danger-soft)] text-semantic-danger">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="mt-4 text-xl font-semibold text-ink-700">This view could not load</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-500">
          The rest of your workspace is still available. Retry this view, or use the navigation to continue elsewhere.
        </p>
        <Button className="mt-5" onClick={reset}>Retry view</Button>
      </div>
    </section>
  );
}
