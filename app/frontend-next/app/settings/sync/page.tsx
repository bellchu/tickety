"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  Clock3,
  Database,
  Download,
  Gauge,
  History,
  MessagesSquare,
  Paperclip,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api, APIError } from "@/lib/api";
import { canAccessAdministration } from "@/lib/auth";
import { formatLocalDateTime, parseApiDateTime } from "@/lib/date-time";
import { formatTimeAgo } from "@/lib/utils";
import { Alert, Button, ErrorState, Skeleton } from "@/components/ui";
import { DiagnosticReveal } from "@/components/admin/DiagnosticReveal";
import { FetchTicketsModal } from "@/components/ticket/FetchTicketsModal";
import {
  ContentSurface,
  PageFrame,
  PageHeader,
  SectionHeader,
  SummaryStrip,
} from "@/components/layout/PageLayout";

function isAuthError(error: unknown) {
  return error instanceof APIError && error.status === 401;
}

function formatDate(value: string | null) {
  return formatLocalDateTime(value, undefined, "Not yet");
}

function formatInclusiveEnd(value: string | null) {
  const exclusiveEnd = parseApiDateTime(value);
  if (!exclusiveEnd) return "Not set";
  return formatLocalDateTime(
    new Date(exclusiveEnd.getTime() - 1),
    { dateStyle: "medium" },
    "Not set",
  );
}

function statusLabel(status: string) {
  if (status === "running") return "Sync running";
  if (status === "throttled") return "Provider pause";
  if (status === "error") return "Needs attention";
  if (status === "success") return "Healthy";
  if (status === "queued") return "Queued";
  return "Waiting to start";
}

export default function TicketSyncStatusPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [oldTicketFetchOpen, setOldTicketFetchOpen] = useState(false);
  const authQuery = useQuery({
    queryKey: ["auth-me"],
    queryFn: api.getAuthMe,
    retry: false,
  });
  const canAccess = canAccessAdministration(authQuery.data);
  const statusQuery = useQuery({
    queryKey: ["sync-status"],
    queryFn: api.getSyncStatus,
    enabled: canAccess,
    refetchInterval: 10_000,
    retry: false,
  });
  const triggerMutation = useMutation({
    mutationFn: api.triggerSync,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });

  const authError = isAuthError(authQuery.error)
    || isAuthError(statusQuery.error)
    || isAuthError(triggerMutation.error);
  useEffect(() => {
    if (authError) router.replace("/login?next=/settings/status/sync");
  }, [authError, router]);

  if (authQuery.isLoading || (canAccess && statusQuery.isLoading)) {
    return <SyncStatusSkeleton />;
  }
  if (authError) return null;
  if (authQuery.isError || !authQuery.data) {
    return (
      <PageFrame>
        <ErrorState
          title="Sync access could not be checked"
          description="Your session could not be verified, so no provider status or controls were requested."
          actionLabel="Retry access check"
          onRetry={() => void authQuery.refetch()}
          retrying={authQuery.isFetching}
        />
      </PageFrame>
    );
  }
  if (!canAccess) {
    return (
      <PageFrame>
        <ErrorState
          title="Administrator access required"
          description="Ticket synchronization status and provider controls are available only to active administrators."
        />
      </PageFrame>
    );
  }
  if (!statusQuery.data) {
    return (
      <PageFrame>
        <ErrorState
          title="Sync status is unavailable"
          description="The current provider state could not be loaded. No provider changes were attempted."
          onRetry={() => void statusQuery.refetch()}
          retrying={statusQuery.isFetching}
        />
      </PageFrame>
    );
  }

  const status = statusQuery.data;
  const remainingPercent = status.rate_limit_total && status.rate_limit_remaining != null
    ? Math.max(0, Math.min(100, (status.rate_limit_remaining / status.rate_limit_total) * 100))
    : null;
  const syncBusy = status.last_status === "running" || status.last_status === "queued";
  const checkedAt = statusQuery.dataUpdatedAt
    ? formatTimeAgo(new Date(statusQuery.dataUpdatedAt).toISOString())
    : "recently";

  return (
    <PageFrame className="max-w-6xl space-y-8">
      <PageHeader
        eyebrow="Settings · Ticketing"
        icon={<Activity className="h-5 w-5" />}
        title="Freshservice sync status"
        description={`Automatic sync is restricted to tickets updated in the last ${status.automatic_fetch_days} days. Older tickets enter a separate queue only after an administrator requests a range.`}
        meta={`Provider: ${status.provider} · checked ${checkedAt}`}
        actions={(
          <>
            <Link href="/settings/status" className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-linen-500 bg-linen-50 px-4 text-sm font-semibold text-ink-700 shadow-sm hover:bg-linen-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2">
              <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Status
            </Link>
            <Button
              variant="secondary"
              onClick={() => void statusQuery.refetch()}
              pending={statusQuery.isFetching}
              pendingLabel="Refreshing…"
              leadingIcon={<RefreshCw className="h-4 w-4" />}
            >
              Refresh
            </Button>
            <Button
              variant="secondary"
              onClick={() => setOldTicketFetchOpen(true)}
              leadingIcon={<Download className="h-4 w-4" />}
            >
              Fetch old tickets
            </Button>
            <Button
              onClick={() => triggerMutation.mutate()}
              disabled={syncBusy}
              pending={triggerMutation.isPending}
              pendingLabel="Starting…"
              leadingIcon={<Activity className="h-4 w-4" />}
            >
              {syncBusy ? "Sync in progress" : "Run bounded sync"}
            </Button>
          </>
        )}
      />

      {statusQuery.error && (
        <Alert
          variant="warning"
          title="The latest sync status refresh failed"
          action={<Button size="sm" variant="secondary" onClick={() => void statusQuery.refetch()} pending={statusQuery.isFetching} pendingLabel="Retrying…">Retry</Button>}
        >
          The last verified provider snapshot remains visible. No synchronization was started by the failed refresh.
        </Alert>
      )}

      {status.last_status === "throttled" && (
        <Alert variant="warning" title="Freshservice requested a pause">
          Tickety will issue no more provider requests until {formatDate(status.next_retry_at)}. This is a normal rate-protection state, not a failed sync.
        </Alert>
      )}
      {status.last_status === "error" && (
        <Alert variant="danger" title="The latest batch needs attention">
          The page checkpoint was retained, so the next run can retry without losing already imported tickets.
        </Alert>
      )}
      {!status.attachment_storage_configured && status.attachment_pending > 0 && (
        <Alert variant="warning" title="Attachment storage is waiting for configuration">
          {status.attachment_pending.toLocaleString()} attachment copies are queued. Configure a private Azure Blob container in Advanced Freshservice Sync to begin copying them.
        </Alert>
      )}
      {status.attachment_errors > 0 && (
        <Alert variant="danger" title="Some attachment copies need attention">
          {status.attachment_errors.toLocaleString()} attachment copies are in an error state. Ticket and conversation checkpoints continue independently.
        </Alert>
      )}
      {(status.last_status === "error" || status.last_status === "throttled" || status.attachment_errors > 0) && (
        <DiagnosticReveal area="sync" />
      )}
      {triggerMutation.isError && (
        <Alert variant="danger" title="The sync could not be started">
          {triggerMutation.error instanceof Error ? triggerMutation.error.message : "Unknown request error"}
        </Alert>
      )}
      {triggerMutation.isSuccess && (
        <Alert variant="success" title="Sync request accepted" action={<Button size="sm" variant="ghost" onClick={() => triggerMutation.reset()}>Dismiss</Button>}>
          The bounded worker run was requested. Live status will update as the queue starts.
        </Alert>
      )}

      <SummaryStrip label="Ticket synchronization overview">
        <Metric label="Local tickets" value={status.local_ticket_count.toLocaleString()} detail={`${status.total_synced.toLocaleString()} source changes applied`} icon={<Database className="h-4 w-4" />} />
        <Metric label="Current lane" value={statusLabel(status.last_status)} detail={status.recent_cycle_started_at ? `Page ${status.recent_page} · started ${formatTimeAgo(status.recent_cycle_started_at)}` : status.recent_completed_at ? `Completed ${formatTimeAgo(status.recent_completed_at)}` : `Page ${status.recent_page}`} icon={<Clock3 className="h-4 w-4" />} />
        <Metric label="Old-ticket request" value={!status.history_requested_at ? "Not requested" : status.history_complete ? "Complete" : `${status.history_processed.toLocaleString()} scanned`} detail={!status.history_requested_at ? "Administrator action required" : status.history_complete ? "Requested range checkpointed" : `Next page ${status.history_page}`} icon={<History className="h-4 w-4" />} />
        <Metric label="API budget" value={status.rate_limit_remaining == null ? "Awaiting headers" : `${status.rate_limit_remaining.toLocaleString()} left`} detail={status.rate_limit_total ? `${Math.round(remainingPercent ?? 0)}% of ${status.rate_limit_total.toLocaleString()} available` : "Reported by Freshservice"} icon={<Gauge className="h-4 w-4" />} />
      </SummaryStrip>

      <ContentSurface className="p-5 sm:p-6">
        <SectionHeader title="Synchronization lanes" description="The automatic and administrator-requested cursors are isolated, and each checkpoint is committed before another Freshservice page is requested." />
        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <LaneCard
            icon={<Clock3 className="h-5 w-5" />}
            title="Current and new tickets"
            state={status.recent_cycle_started_at ? "In progress" : "Caught up"}
            detail={status.recent_cycle_started_at
              ? `Updated since ${formatDate(status.recent_since_at)} · page ${status.recent_page}`
              : `Last completed ${formatDate(status.recent_completed_at)}`}
            policy={`Automatic ${status.automatic_fetch_days}-day window · ${status.recent_pages_per_sync} page${status.recent_pages_per_sync === 1 ? "" : "s"} per run`}
          />
          <LaneCard
            icon={<History className="h-5 w-5" />}
            title="Older tickets"
            state={!status.history_requested_at ? "Admin only" : status.history_complete ? "Complete" : "Requested import"}
            detail={!status.history_requested_at
              ? "No older-ticket range is queued"
              : `${formatDate(status.history_since_at)} to ${formatInclusiveEnd(status.history_until_at)} · ${status.history_processed.toLocaleString()} scanned`}
            policy={`2 months, 3 months, or custom dates · ${status.history_pages_per_sync} page${status.history_pages_per_sync === 1 ? "" : "s"} per run`}
          />
          <LaneCard
            icon={<MessagesSquare className="h-5 w-5" />}
            title="Conversation threads"
            state="Newest first"
            detail={`${status.conversations_processed.toLocaleString()} ticket threads hydrated`}
            policy={`${status.conversations_per_sync} thread${status.conversations_per_sync === 1 ? "" : "s"} admitted per run`}
          />
          <LaneCard
            icon={<Paperclip className="h-5 w-5" />}
            title="Original attachments"
            state={status.attachment_storage_configured ? "Private storage" : "Storage not configured"}
            detail={`${status.attachment_stored.toLocaleString()} stored · ${status.attachment_pending.toLocaleString()} pending · ${status.attachment_errors.toLocaleString()} errors`}
            policy={`${status.attachments_per_sync} attachment${status.attachments_per_sync === 1 ? "" : "s"} copied per run`}
          />
        </div>
      </ContentSurface>

      <div className="grid gap-4 lg:grid-cols-2">
        <ContentSurface className="p-5 sm:p-6">
          <SectionHeader title="Latest batch" description={`Runs every ${status.sync_interval_seconds} seconds when the worker is ready.`} />
          <dl className="mt-5 divide-y divide-linen-300 text-sm">
            <Detail label="Started" value={formatDate(status.run_started_at)} />
            <Detail label="Finished" value={formatDate(status.run_finished_at)} />
            <Detail label="New tickets" value={status.last_batch_new.toLocaleString()} />
            <Detail label="Updated tickets" value={status.last_batch_updated.toLocaleString()} />
            <Detail label="Record errors" value={status.last_batch_errors.toLocaleString()} />
          </dl>
        </ContentSurface>
        <ContentSurface className="p-5 sm:p-6">
          <SectionHeader title="Provider protection" description="Freshservice headers are authoritative for the shared account budget." />
          <div className="mt-5 flex items-start gap-3 rounded-xl border border-moss-500/25 bg-moss-500/10 p-4">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-moss-600" />
            <div>
              <p className="text-sm font-semibold text-ink-700">Bounded and resumable</p>
              <p className="mt-1 text-xs leading-5 text-ink-500">List requests are paced, resource embeds are excluded from discovery, low remaining capacity pauses the queue, and `Retry-After` survives worker restarts.</p>
            </div>
          </div>
          <dl className="mt-3 divide-y divide-linen-300 text-sm">
            <Detail label="Last request cost" value={status.rate_limit_used == null ? "Not reported" : `${status.rate_limit_used} credit${status.rate_limit_used === 1 ? "" : "s"}`} />
            <Detail label="Next allowed request" value={status.next_retry_at ? formatDate(status.next_retry_at) : "Ready"} />
          </dl>
        </ContentSurface>
      </div>
      <FetchTicketsModal open={oldTicketFetchOpen} onClose={() => setOldTicketFetchOpen(false)} />
    </PageFrame>
  );
}

function Metric({ label, value, detail, icon }: { label: string; value: string; detail: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">{icon}{label}</div>
      <p className="mt-3 text-2xl font-semibold tracking-[-0.035em] text-ink-700">{value}</p>
      <p className="mt-1 text-xs leading-5 text-ink-500">{detail}</p>
    </div>
  );
}

function LaneCard({ icon, title, state, detail, policy }: { icon: React.ReactNode; title: string; state: string; detail: string; policy: string }) {
  return (
    <article className="min-w-0 rounded-xl border border-linen-400 bg-linen-100 p-4">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <span className="text-semantic-primary">{icon}</span>
        <span className="max-w-full break-words rounded-full bg-linen-300 px-2.5 py-1 text-[11px] font-semibold text-ink-600 [overflow-wrap:anywhere]" title={state}>{state}</span>
      </div>
      <h3 className="mt-4 text-sm font-semibold text-ink-700">{title}</h3>
      <p className="mt-1 break-words text-xs leading-5 text-ink-500 [overflow-wrap:anywhere]">{detail}</p>
      <p className="mt-3 break-words border-t border-linen-300 pt-3 text-[11px] font-medium text-ink-400 [overflow-wrap:anywhere]">{policy}</p>
    </article>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-1 py-3"><dt className="text-ink-500">{label}</dt><dd className="min-w-0 break-words text-right font-medium text-ink-700 [overflow-wrap:anywhere]" title={value}>{value}</dd></div>;
}

function SyncStatusSkeleton() {
  return (
    <PageFrame className="max-w-6xl space-y-8" aria-busy="true" aria-label="Loading ticket sync status">
      <div className="space-y-3 border-b border-linen-400 pb-6"><Skeleton className="h-3 w-36" /><Skeleton className="h-10 w-80" /><Skeleton className="h-4 w-full max-w-2xl" /></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-32" rounded="lg" />)}</div>
      <Skeleton className="h-72" rounded="lg" />
    </PageFrame>
  );
}
