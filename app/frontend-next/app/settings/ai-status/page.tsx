"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Bot,
  CalendarClock,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Cpu,
  ExternalLink,
  ListChecks,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { api, APIError } from "@/lib/api";
import { canAccessAdministration } from "@/lib/auth";
import { formatLocalDateTime, parseApiDateTime, resolvedLocalTimeZone, toLocalDateTimeInput } from "@/lib/date-time";
import {
  aiArtifactLabel,
  aiCallStatusMeta,
  aiTaskLifecycleMeta,
  operationalCodeLabel,
} from "@/lib/ai-status";
import type { AILLMCallStatusItem, AIRetryQueueActionResponse, AITaskLifecycle, AITaskStatusItem, AITaskView, AIStatusResponse } from "@/lib/types";
import { formatTimeAgo } from "@/lib/utils";
import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, ErrorState, ListText, Skeleton } from "@/components/ui";
import { DiagnosticReveal } from "@/components/admin/DiagnosticReveal";
import {
  ContentSurface,
  DataToolbar,
  PageFrame,
  PageHeader,
  SectionHeader,
  SummaryStrip,
} from "@/components/layout/PageLayout";

const PAGE_SIZE = 25;
const DIAGNOSTIC_LIFECYCLES = new Set<AITaskLifecycle>([
  "retry_scheduled",
  "lease_expired",
  "partial",
  "stale",
  "failed",
  "dead_letter",
  "paused",
  "unknown",
]);

const views: Array<{ value: AITaskView; label: string }> = [
  { value: "active", label: "Active" },
  { value: "retry_scheduled", label: "Scheduled retries" },
  { value: "attention", label: "Needs attention" },
  { value: "completed", label: "Completed" },
  { value: "not_analyzed", label: "Not analyzed" },
  { value: "not_applicable", label: "Historical" },
  { value: "all", label: "All tickets" },
];

function isAuthError(error: unknown) {
  return error instanceof APIError && error.status === 401;
}

function formatDate(value: string | null) {
  return formatLocalDateTime(value, undefined, "Not available");
}

function viewCount(data: AIStatusResponse, view: AITaskView) {
  if (view === "all") return data.queue.total_tickets;
  if (view === "active") return data.queue.queued + data.queue.running;
  if (view === "retry_scheduled") return data.queue.retry_scheduled;
  if (view === "attention") return data.queue.attention;
  if (view === "completed") return data.queue.completed;
  if (view === "not_analyzed") return data.queue.not_analyzed;
  return data.queue.not_applicable;
}

function retryActionNotice(result: AIRetryQueueActionResponse) {
  const count = result.affected.toLocaleString();
  const message = {
    clear: `${count} scheduled retr${result.affected === 1 ? "y was" : "ies were"} paused, removed from the active queue, and cleared from attention.`,
    retry_all_now: `${count} scheduled retr${result.affected === 1 ? "y is" : "ies are"} ready for worker claims.`,
    retry_now: "The retry is ready for a worker claim.",
    reschedule: `The retry was rescheduled for ${formatDate(result.scheduled_at)}.`,
  }[result.action];
  if (!result.dispatch_blocked_until) return message;
  return `${message} Provider dispatch remains paused until ${formatDate(result.dispatch_blocked_until)}.`;
}

type BulkRetryAction = "retry_all_now" | "clear";
type TaskRetryAction =
  | { action: "retry_now"; ticketId: string }
  | { action: "reschedule"; ticketId: string; scheduledAt: string };

function taskTiming(task: AITaskStatusItem) {
  if (task.lifecycle === "retry_scheduled") return `Retry ${formatDate(task.next_attempt_at)}`;
  if (task.lifecycle === "running") return task.started_at ? `Started ${formatTimeAgo(task.started_at)}` : "Worker active";
  if (task.lifecycle === "lease_expired") return `Lease ended ${formatDate(task.lease_expires_at)}`;
  if (task.generated_at) return `Generated ${formatTimeAgo(task.generated_at)}`;
  if (task.updated_at) return `Updated ${formatTimeAgo(task.updated_at)}`;
  return `Created ${formatTimeAgo(task.created_at)}`;
}

function humanizeTaskName(value: string) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .trim() || "AI request";
}

export default function AIStatusPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [view, setView] = useState<AITaskView>("active");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [bulkAction, setBulkAction] = useState<BulkRetryAction | null>(null);
  const [scheduleTask, setScheduleTask] = useState<AITaskStatusItem | null>(null);
  const [scheduleInput, setScheduleInput] = useState("");
  const [actionResult, setActionResult] = useState<AIRetryQueueActionResponse | null>(null);
  const authQuery = useQuery({
    queryKey: ["auth-me"],
    queryFn: api.getAuthMe,
    retry: false,
  });
  const canAccess = canAccessAdministration(authQuery.data);
  const statusQuery = useQuery({
    queryKey: ["ai-task-status", view, search, offset, PAGE_SIZE],
    queryFn: () => api.getAIStatus({ view, search, limit: PAGE_SIZE, offset }),
    enabled: canAccess,
    retry: false,
    refetchInterval: 10_000,
  });
  const invalidateAIQueue = () => {
    void queryClient.invalidateQueries({ queryKey: ["ai-task-status"] });
    void queryClient.invalidateQueries({ queryKey: ["tickets"] });
  };
  const bulkMutation = useMutation({
    mutationFn: (action: BulkRetryAction) => action === "clear"
      ? api.clearScheduledAIRetries()
      : api.retryAllScheduledAINow(),
    onSuccess: (result) => {
      setActionResult(result);
      setBulkAction(null);
      invalidateAIQueue();
    },
  });
  const taskMutation = useMutation({
    mutationFn: (input: TaskRetryAction) => input.action === "retry_now"
      ? api.retryAITaskNow(input.ticketId)
      : api.rescheduleAITask(input.ticketId, input.scheduledAt),
    onSuccess: (result) => {
      setActionResult(result);
      setScheduleTask(null);
      invalidateAIQueue();
    },
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    const totalTasks = statusQuery.data?.total_tasks;
    if (totalTasks === undefined || offset === 0 || offset < totalTasks) return;
    const lastPageOffset = totalTasks === 0
      ? 0
      : Math.floor((totalTasks - 1) / PAGE_SIZE) * PAGE_SIZE;
    setOffset(lastPageOffset);
  }, [offset, statusQuery.data?.total_tasks]);

  const authError = isAuthError(authQuery.error)
    || isAuthError(statusQuery.error)
    || isAuthError(bulkMutation.error)
    || isAuthError(taskMutation.error);
  useEffect(() => {
    if (authError) router.replace("/login?next=/settings/status/ai");
  }, [authError, router]);

  const selectView = (next: AITaskView) => {
    setView(next);
    setOffset(0);
  };
  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setSearch(searchInput.trim());
    setOffset(0);
  };
  const openBulkAction = (action: BulkRetryAction) => {
    bulkMutation.reset();
    taskMutation.reset();
    setActionResult(null);
    setBulkAction(action);
  };
  const openSchedule = (task: AITaskStatusItem) => {
    taskMutation.reset();
    setActionResult(null);
    setScheduleTask(task);
    const snapshotNow = parseApiDateTime(statusQuery.data?.generated_at)
      || parseApiDateTime(task.updated_at)
      || new Date();
    setScheduleInput(toLocalDateTimeInput(
      task.next_attempt_at || new Date(snapshotNow.getTime() + 15 * 60_000),
    ));
  };
  const retryTaskNow = (task: AITaskStatusItem) => {
    taskMutation.reset();
    setActionResult(null);
    taskMutation.mutate({ action: "retry_now", ticketId: task.ticket_id });
  };
  const submitSchedule = () => {
    if (!scheduleTask || !scheduleInput) return;
    const scheduledAt = new Date(scheduleInput);
    if (Number.isNaN(scheduledAt.getTime())) return;
    taskMutation.mutate({
      action: "reschedule",
      ticketId: scheduleTask.ticket_id,
      scheduledAt: scheduledAt.toISOString(),
    });
  };

  if (authQuery.isLoading || (canAccess && statusQuery.isLoading)) return <AIStatusSkeleton />;
  if (authError) return null;
  if (authQuery.isError || !authQuery.data) {
    return (
      <PageFrame>
        <ErrorState
          title="AI status access could not be checked"
          description="Your session could not be verified, so no administrative AI data was requested."
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
          description="AI task status contains workspace-wide operational details and is available only to active administrators."
        />
      </PageFrame>
    );
  }
  if (!statusQuery.data) {
    return (
      <PageFrame>
        <ErrorState
          title="AI task status is unavailable"
          description="The durable task queue could not be loaded. No AI work was changed."
          onRetry={() => void statusQuery.refetch()}
          retrying={statusQuery.isFetching}
        />
      </PageFrame>
    );
  }

  const data = statusQuery.data;
  const enabledFeatures = data.automation.filter((feature) => feature.enabled);
  const activeTasks = data.queue.queued + data.queue.running;
  const hasNextPage = offset + data.tasks.length < data.total_tasks;
  const firstResult = data.total_tasks ? offset + 1 : 0;
  const lastResult = offset + data.tasks.length;
  const snapshotNow = parseApiDateTime(data.generated_at) || new Date();
  const snapshotNowMs = snapshotNow.getTime();
  const maximumScheduleMs = snapshotNowMs + 365 * 24 * 60 * 60_000;
  const minimumSchedule = toLocalDateTimeInput(new Date(snapshotNowMs + 60_000));
  const maximumSchedule = toLocalDateTimeInput(new Date(maximumScheduleMs));
  const parsedSchedule = scheduleInput ? new Date(scheduleInput) : null;
  const scheduleIsValid = Boolean(
    parsedSchedule
    && !Number.isNaN(parsedSchedule.getTime())
    && parsedSchedule.getTime() > snapshotNowMs
    && parsedSchedule.getTime() <= maximumScheduleMs,
  );

  return (
    <PageFrame width="wide" className="space-y-8">
      <PageHeader
        eyebrow="Settings · AI operations"
        icon={<Bot className="h-5 w-5" />}
        title="AI task status"
        description="Inspect durable ticket-analysis work, retry and lease health, enabled automation, and prompt-free provider-call telemetry."
        meta={`Live refresh every 10 seconds · snapshot ${formatTimeAgo(data.generated_at)}`}
        actions={(
          <div className="flex flex-wrap gap-2">
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
          </div>
        )}
      />

      {statusQuery.error && (
        <Alert
          variant="warning"
          title="The latest AI status refresh failed"
          action={<Button size="sm" variant="secondary" onClick={() => void statusQuery.refetch()} pending={statusQuery.isFetching} pendingLabel="Retrying…">Retry</Button>}
        >
          The last verified snapshot remains visible. No queue action was attempted by the failed refresh.
        </Alert>
      )}

      {data.provider_cooldown && (
        <Alert variant="info" title="Provider capacity pause is active">
          Background admission is paused across all workers, so the backlog will not generate repeated attempts. Dispatch resumes after {formatDate(data.provider_cooldown.retry_at)}.
        </Alert>
      )}
      {data.queue.attention > 0 && (
        <Alert variant="warning" title={`${data.queue.attention.toLocaleString()} task${data.queue.attention === 1 ? "" : "s"} need attention`}>
          This includes exhausted retries, partial or stale results, unplanned paused work, and expired worker leases. Retries deliberately cleared by an administrator are excluded.
        </Alert>
      )}
      {enabledFeatures.length === 0 && (
        <Alert variant="info" title="Automatic AI is off">
          New tickets will not be admitted automatically. Authenticated users can still run analysis from a ticket, and already queued work remains visible here.
        </Alert>
      )}

      <SummaryStrip label="AI operations overview">
        <MetricCard
          label="Active tasks"
          value={activeTasks.toLocaleString()}
          detail={`${data.queue.queued_ready.toLocaleString()} ready · ${data.queue.retry_scheduled.toLocaleString()} delayed · ${data.queue.running_active.toLocaleString()} running`}
          icon={<Activity className="h-4 w-4" />}
          tone="info"
        />
        <MetricCard
          label="Needs attention"
          value={data.queue.attention.toLocaleString()}
          detail={`${data.queue.dead_letter.toLocaleString()} exhausted · ${data.queue.lease_expired.toLocaleString()} expired leases`}
          icon={<AlertTriangle className="h-4 w-4" />}
          tone={data.queue.attention ? "danger" : "success"}
        />
        <MetricCard
          label="Completed"
          value={data.queue.completed.toLocaleString()}
          detail={`${data.queue.not_analyzed.toLocaleString()} active not analyzed · ${data.queue.not_applicable.toLocaleString()} historical`}
          icon={<CheckCircle2 className="h-4 w-4" />}
          tone="success"
        />
        <MetricCard
          label="Provider calls · 24h"
          value={data.calls_24h.calls.toLocaleString()}
          detail={`${data.calls_24h.successful.toLocaleString()} successful · ${data.calls_24h.deferred.toLocaleString()} safely deferred · ${data.calls_24h.total_tokens.toLocaleString()} tokens`}
          icon={<Cpu className="h-4 w-4" />}
          tone="neutral"
        />
      </SummaryStrip>

      <ContentSurface className="p-5 sm:p-6">
        <SectionHeader
          title="Scheduled retry controls"
          description="Operate on delayed ticket-analysis retries without deleting tickets or generated AI artifacts."
          actions={<Badge variant={data.queue.retry_scheduled ? "warning" : "success"} dot>{data.queue.retry_scheduled.toLocaleString()} delayed</Badge>}
        />
        <div className="mt-5 flex flex-col gap-4 rounded-xl border border-linen-400 bg-linen-100 p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink-700">Queue-wide actions</p>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-ink-500">
              Retry all makes every delayed task ready now. Clear queue moves delayed tasks to Paused and removes them from attention; an administrator can still reschedule or resume them later.
            </p>
            {data.provider_cooldown && (
              <p className="mt-2 text-xs font-medium text-semantic-info">
                Provider safety pause remains active until {formatDate(data.provider_cooldown.retry_at)} and is not bypassed by these controls.
              </p>
            )}
          </div>
          <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
            <Button
              variant="secondary"
              disabled={data.queue.retry_scheduled === 0}
              onClick={() => openBulkAction("retry_all_now")}
              leadingIcon={<Play className="h-4 w-4" />}
            >
              Retry all now
            </Button>
            <Button
              variant="destructive"
              disabled={data.queue.retry_scheduled === 0}
              onClick={() => openBulkAction("clear")}
              leadingIcon={<Trash2 className="h-4 w-4" />}
            >
              Pause scheduled retries
            </Button>
          </div>
        </div>
        {actionResult && (
          <Alert className="mt-4" variant="success" title="Retry queue updated">
            {retryActionNotice(actionResult)}
          </Alert>
        )}
        {(bulkMutation.error || taskMutation.error) && (
          <Alert className="mt-4" variant="danger" title="Retry queue was not changed">
            {(bulkMutation.error || taskMutation.error) instanceof Error
              ? (bulkMutation.error || taskMutation.error)?.message
              : "The administrator action could not be completed."}
          </Alert>
        )}
      </ContentSurface>

      <ContentSurface className="p-5 sm:p-6">
        <SectionHeader
          title="Automation readiness"
          description="Global feature switches and integration admission are separate safety boundaries."
          actions={<Link href="/settings#settings-automation" className="rounded-sm text-xs font-semibold text-semantic-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2">Change automation settings</Link>}
        />
        <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.45fr)]">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {data.automation.map((feature) => (
              <div key={feature.key} className="rounded-xl border border-linen-400 bg-linen-100 p-3">
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <ListText text={feature.label} lines={2} className="min-w-0 flex-1 text-sm font-semibold text-ink-700" />
                  <Badge className="shrink-0" variant={feature.enabled ? "success" : "neutral"} dot>{feature.enabled ? "On" : "Off"}</Badge>
                </div>
                <p className="mt-2 text-xs text-ink-400">{feature.enabled ? "Eligible for automatic work" : "Manual requests only"}</p>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-linen-400 bg-linen-100 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">Integration admission</p>
            <div className="mt-3 flex items-end justify-between gap-4">
              <div>
                <p className="text-2xl font-semibold tracking-[-0.03em] text-ink-700">{data.automatic_ai_bindings}</p>
                <p className="mt-1 text-xs text-ink-500">automatic AI bindings</p>
              </div>
              <p className="text-right text-xs leading-5 text-ink-400">{data.active_integration_bindings} active integration{data.active_integration_bindings === 1 ? "" : "s"}</p>
            </div>
            <p className="mt-3 border-t border-linen-400 pt-3 text-xs leading-5 text-ink-500">
              {data.active_routing_backlog_enabled
                ? "Older active tickets are admitted for staged triage and routing."
                : "Automatic external analysis is limited to the seven-day realtime window."}
            </p>
          </div>
        </div>
      </ContentSurface>

      <DataToolbar label="Filter AI ticket tasks">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">Task view</p>
            <div className="mt-2 flex gap-1 overflow-x-auto pb-1" role="group" aria-label="AI task status views">
              {views.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  aria-pressed={view === item.value}
                  onClick={() => selectView(item.value)}
                  className={`inline-flex min-h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors ${view === item.value ? "bg-ink-700 text-white" : "bg-linen-200 text-ink-500 hover:bg-linen-300 hover:text-ink-700"}`}
                >
                  {item.label}
                  <span className={view === item.value ? "text-white/70" : "text-ink-400"}>{viewCount(data, item.value).toLocaleString()}</span>
                </button>
              ))}
            </div>
          </div>
          <form onSubmit={submitSearch} className="flex w-full max-w-md gap-2" role="search">
            <label className="relative min-w-0 flex-1">
              <span className="sr-only">Search AI tasks</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Ticket subject, Tickety ID, or external ID"
                className="input-base pl-9"
              />
            </label>
            <Button type="submit" variant="secondary">Search</Button>
          </form>
        </div>
      </DataToolbar>

      <ContentSurface>
        <div className="border-b border-linen-400 p-5 sm:p-6">
          <SectionHeader
            title="Ticket analysis tasks"
            description={data.total_tasks
              ? `Showing ${firstResult.toLocaleString()}–${lastResult.toLocaleString()} of ${data.total_tasks.toLocaleString()} matching tickets.`
              : "No tickets match this task view."}
            actions={data.queue.oldest_queued_at ? <span className="text-xs text-ink-400">Oldest queued {formatTimeAgo(data.queue.oldest_queued_at)}</span> : undefined}
          />
        </div>
        {data.tasks.length ? (
          <div className="divide-y divide-linen-300">
            {data.tasks.map((task) => (
              <TaskRow
                key={task.ticket_id}
                task={task}
                onRetryNow={() => retryTaskNow(task)}
                onReschedule={() => openSchedule(task)}
                pendingAction={taskMutation.isPending && taskMutation.variables?.ticketId === task.ticket_id
                  ? taskMutation.variables.action
                  : null}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            className="m-5 sm:m-6"
            icon={<ListChecks className="h-5 w-5" />}
            title={search ? "No matching AI tasks" : "This task view is clear"}
            description={search ? "Try a different ticket subject or identifier." : "No tickets currently have this lifecycle state."}
          />
        )}
        {data.total_tasks > PAGE_SIZE && (
          <nav aria-label="AI task pages" className="flex items-center justify-between border-t border-linen-400 px-5 py-4 sm:px-6">
            <p className="text-xs text-ink-400" aria-live="polite">Page {Math.floor(offset / PAGE_SIZE) + 1}</p>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} leadingIcon={<ChevronLeft className="h-4 w-4" />}>Previous</Button>
              <Button variant="secondary" size="sm" disabled={!hasNextPage} onClick={() => setOffset(offset + PAGE_SIZE)}>Next <ChevronRight className="h-4 w-4" /></Button>
            </div>
          </nav>
        )}
      </ContentSurface>

      <ContentSurface>
        <div className="border-b border-linen-400 p-5 sm:p-6">
          <SectionHeader
            title="Recent provider calls"
            description="Durable execution telemetry only. Prompts, ticket text, model output, and secrets are never included."
            actions={<span className="text-xs text-ink-400">Average latency {data.calls_24h.average_latency_ms.toLocaleString()} ms</span>}
          />
        </div>
        {data.recent_calls.length ? (
          <div className="divide-y divide-linen-300">
            {data.recent_calls.map((call) => <ProviderCallRow key={call.id} call={call} />)}
          </div>
        ) : (
          <EmptyState
            className="m-5 sm:m-6"
            icon={<Sparkles className="h-5 w-5" />}
            title="No durable provider calls yet"
            description="Calls will appear after persistent LLM metrics are enabled and an AI task reaches the configured provider."
          />
        )}
      </ContentSurface>

      <ConfirmDialog
        open={bulkAction !== null}
        onOpenChange={(open) => {
          if (!open) setBulkAction(null);
        }}
        title={bulkAction === "clear" ? "Pause all scheduled retries?" : "Retry all scheduled tasks now?"}
        description={bulkAction === "clear"
          ? `${data.queue.retry_scheduled.toLocaleString()} delayed task${data.queue.retry_scheduled === 1 ? "" : "s"} will move to Paused and no longer count as needing attention. Tickets, requested artifacts, attempt counts, and existing AI results are retained.`
          : `${data.queue.retry_scheduled.toLocaleString()} delayed task${data.queue.retry_scheduled === 1 ? "" : "s"} will become ready for worker claims. The provider safety pause, if active, still controls actual dispatch.`}
        confirmLabel={bulkAction === "clear" ? "Pause retries" : "Retry all now"}
        destructive={bulkAction === "clear"}
        pending={bulkMutation.isPending}
        onConfirm={() => {
          if (bulkAction) bulkMutation.mutate(bulkAction);
        }}
      />

      <Dialog
        open={scheduleTask !== null}
        onOpenChange={(open) => {
          if (!open && !taskMutation.isPending) setScheduleTask(null);
        }}
        title="Change retry time"
        description={scheduleTask ? `Choose when “${scheduleTask.subject}” becomes eligible for another worker claim.` : undefined}
        closeOnBackdrop={!taskMutation.isPending}
        dismissible={!taskMutation.isPending}
        footer={(
          <>
            <Button variant="secondary" disabled={taskMutation.isPending} onClick={() => setScheduleTask(null)}>Cancel</Button>
            <Button
              pending={taskMutation.isPending}
              pendingLabel="Rescheduling…"
              disabled={!scheduleIsValid}
              onClick={submitSchedule}
              leadingIcon={<CalendarClock className="h-4 w-4" />}
            >
              Save retry time
            </Button>
          </>
        )}
      >
        <label className="block">
          <span className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-400">Scheduled time</span>
          <input
            type="datetime-local"
            className="input-base mt-2"
            value={scheduleInput}
            min={minimumSchedule}
            max={maximumSchedule}
            onChange={(event) => setScheduleInput(event.target.value)}
          />
        </label>
        <p className="mt-2 text-xs leading-5 text-ink-400">
          Times are entered in {resolvedLocalTimeZone()} and stored as UTC. Use “Retry now” instead of selecting a past time.
        </p>
        {taskMutation.error && (
          <Alert className="mt-4" variant="danger" title="Retry time was not changed">
            {taskMutation.error instanceof Error ? taskMutation.error.message : "The retry could not be rescheduled."}
          </Alert>
        )}
      </Dialog>
    </PageFrame>
  );
}

function TaskRow({
  task,
  onRetryNow,
  onReschedule,
  pendingAction,
}: {
  task: AITaskStatusItem;
  onRetryNow: () => void;
  onReschedule: () => void;
  pendingAction: TaskRetryAction["action"] | null;
}) {
  const lifecycle = aiTaskLifecycleMeta(task.lifecycle);
  const canControlRetry = (
    task.lifecycle === "retry_scheduled" || task.lifecycle === "paused"
  ) && task.requested_artifacts.length > 0;
  return (
    <details className="group px-5 py-4 open:bg-linen-100 sm:px-6">
      <summary className="cursor-pointer list-none rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(180px,0.55fr)_minmax(210px,0.7fr)_minmax(130px,0.4fr)] lg:items-center">
          <div className="min-w-0">
            <div className="flex min-w-0 items-start gap-2">
              <ListText text={task.subject} lines={2} className="min-w-0 flex-1 text-sm font-semibold leading-5 text-ink-700" />
              {task.synthetic && <Badge className="shrink-0" variant="warning">Synthetic</Badge>}
            </div>
            <ListText text={`${task.external_id || task.ticket_id} · ${task.source}`} lines="wrap" className="mt-1 font-mono text-[11px] text-ink-400" />
          </div>
          <div>
            <Badge variant={lifecycle.variant} dot>{lifecycle.label}</Badge>
            <ListText text={taskTiming(task)} lines={2} className="mt-1.5 text-[11px] text-ink-400" />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {task.requested_artifacts.length
              ? task.requested_artifacts.map((artifact) => <Badge key={artifact}>{aiArtifactLabel(artifact)}</Badge>)
              : <span className="text-xs text-ink-400">No pending artifacts</span>}
          </div>
          <div className="flex items-center justify-between gap-3 lg:justify-end">
            <span className="text-xs text-ink-400">{task.attempts} attempt{task.attempts === 1 ? "" : "s"}</span>
            <span className="text-xs font-semibold text-semantic-primary group-open:hidden">Details</span>
            <span className="hidden text-xs font-semibold text-semantic-primary group-open:inline">Close</span>
          </div>
        </div>
      </summary>
      <div className="mt-4 border-t border-linen-300 pt-4">
        <p className="text-xs leading-5 text-ink-500">{lifecycle.description}</p>
        <dl className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <TaskDetail label="Execution" value={`Started: ${formatDate(task.started_at)}\nLease: ${formatDate(task.lease_expires_at)}\nRetry: ${formatDate(task.next_attempt_at)}`} />
          <TaskDetail label="Result" value={`Generated: ${formatDate(task.generated_at)}\nModel: ${task.model || "Not recorded"}`} />
          <TaskDetail label="Ticket" value={`Priority: ${task.priority}\nWorkflow: ${task.ticket_status}\nCreated: ${formatDate(task.created_at)}`} />
          <TaskDetail label="Last safe error" value={operationalCodeLabel(task.error_code)} danger={Boolean(task.error_code)} />
        </dl>
        {DIAGNOSTIC_LIFECYCLES.has(task.lifecycle) && (
          <DiagnosticReveal ticketId={task.ticket_id} className="mt-4" />
        )}
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          {canControlRetry ? (
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                size="sm"
                pending={pendingAction === "retry_now"}
                pendingLabel="Queueing…"
                disabled={pendingAction !== null}
                onClick={onRetryNow}
                leadingIcon={<Play className="h-3.5 w-3.5" />}
              >
                Retry now
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={pendingAction !== null}
                onClick={onReschedule}
                leadingIcon={<CalendarClock className="h-3.5 w-3.5" />}
              >
                Change time
              </Button>
            </div>
          ) : <span />}
          <Link href={`/tickets/${encodeURIComponent(task.ticket_id)}`} className="inline-flex min-h-9 items-center gap-2 rounded-md border border-linen-500 bg-linen-50 px-3 text-xs font-semibold text-ink-700 hover:bg-linen-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2">
            Open ticket <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </details>
  );
}

function TaskDetail({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-400">{label}</dt>
      <dd className={`mt-1 whitespace-pre-line break-words text-xs leading-5 [overflow-wrap:anywhere] ${danger ? "text-rust-600" : "text-ink-600"}`}>{value}</dd>
    </div>
  );
}

function ProviderCallRow({ call }: { call: AILLMCallStatusItem }) {
  const status = aiCallStatusMeta(call.status);
  return (
    <div className="grid gap-3 px-5 py-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(160px,0.45fr)_minmax(170px,0.5fr)_minmax(140px,0.4fr)] lg:items-center">
      <div className="min-w-0">
        <div className="flex min-w-0 items-start gap-2">
          <ListText text={humanizeTaskName(call.task)} lines={2} className="min-w-0 flex-1 text-sm font-semibold leading-5 text-ink-700" />
          {call.synthetic && <Badge className="shrink-0" variant="warning">Synthetic</Badge>}
        </div>
        <ListText text={`${call.provider} · ${call.model}`} lines={2} className="mt-1 font-mono text-[11px] text-ink-400" />
      </div>
      <div><Badge variant={status.variant} dot>{status.label}</Badge></div>
      <p className="break-words text-xs leading-5 text-ink-500 [overflow-wrap:anywhere]">
        {call.latency_ms.toLocaleString()} ms · {call.total_tokens.toLocaleString()} actual / {call.estimated_tokens.toLocaleString()} estimated tokens · {call.attempts} attempt{call.attempts === 1 ? "" : "s"}
        <span className="block text-[11px] text-ink-400">
          {call.dispatched ? "Provider dispatched" : "Deferred before dispatch"}
          {call.http_status ? ` · HTTP ${call.http_status}` : ""}
          {call.failure_kind ? ` · ${operationalCodeLabel(call.failure_kind)}` : ""}
          {call.retry_after_seconds ? ` · retry after ${call.retry_after_seconds}s` : ""}
        </span>
      </p>
      <div className="lg:text-right">
        <p className="text-xs text-ink-500">{formatTimeAgo(call.created_at)}</p>
        {call.error_code && <ListText text={operationalCodeLabel(call.error_code)} lines={2} className="mt-1 text-[11px] text-rust-600" />}
      </div>
    </div>
  );
}

function MetricCard({ label, value, detail, icon, tone }: { label: string; value: string; detail: string; icon: React.ReactNode; tone: "neutral" | "info" | "success" | "danger" }) {
  const iconTone = {
    neutral: "bg-linen-300 text-ink-500",
    info: "bg-[var(--color-info-soft)] text-semantic-info",
    success: "bg-[var(--color-success-soft)] text-semantic-success",
    danger: "bg-[var(--color-danger-soft)] text-semantic-danger",
  }[tone];
  return (
    <div className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</p>
        <span className={`grid h-8 w-8 place-items-center rounded-lg ${iconTone}`} aria-hidden="true">{icon}</span>
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-[-0.035em] text-ink-700">{value}</p>
      <p className="mt-1 text-xs leading-5 text-ink-500">{detail}</p>
    </div>
  );
}

function AIStatusSkeleton() {
  return (
    <PageFrame width="wide" aria-busy="true" aria-label="Loading AI task status">
      <div className="space-y-3 border-b border-linen-400 pb-6"><Skeleton className="h-3 w-36" /><Skeleton className="h-10 w-72" /><Skeleton className="h-4 w-full max-w-2xl" /></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-32" rounded="lg" />)}</div>
      <Skeleton className="h-40" rounded="lg" />
      <Skeleton className="h-80" rounded="lg" />
    </PageFrame>
  );
}
