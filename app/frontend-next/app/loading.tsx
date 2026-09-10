import { Skeleton } from "@/components/ui/Feedback";

export default function Loading() {
  return (
    <div className="mx-auto w-full max-w-7xl space-y-6" aria-busy="true" aria-label="Loading view">
      <div className="space-y-3 border-b border-linen-400 pb-6">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-9 w-full max-w-md" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-24" rounded="lg" />
        ))}
      </div>
      <Skeleton className="h-64" rounded="lg" />
      <span className="sr-only">Loading Tickety OPS Tower workspace…</span>
    </div>
  );
}
