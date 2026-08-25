"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock3,
  Cloud,
  Database,
  HardDrive,
  KeyRound,
  RefreshCw,
  Server,
  TriangleAlert,
} from "lucide-react";
import { api, APIError } from "@/lib/api";
import { canAccessAdministration } from "@/lib/auth";
import type { OperationalDiagnosticArea } from "@/lib/types";
import { formatTimeAgo } from "@/lib/utils";
import { Alert, Badge, Button, ErrorState, Skeleton } from "@/components/ui";
import { DiagnosticReveal } from "@/components/admin/DiagnosticReveal";
import { ContentSurface, PageFrame, PageHeader, SectionHeader, SummaryStrip } from "@/components/layout/PageLayout";

type StatusTone = "healthy" | "active" | "warning" | "neutral" | "unavailable";

function isAuthError(error: unknown) {
  return error instanceof APIError && error.status === 401;
}

function syncTone(status?: string): StatusTone {
  if (!status || status === "idle") return "neutral";
  if (status === "error" || status === "throttled") return "warning";
  if (status === "running" || status === "queued") return "active";
  return "healthy";
}

function syncLabel(status?: string) {
  if (!status || status === "idle") return "Waiting to start";
  if (status === "error") return "Needs attention";
  if (status === "throttled") return "Provider pause";
  if (status === "running") return "Sync running";
  if (status === "queued") return "Queued";
  if (status === "success") return "Healthy";
  return status.replaceAll("_", " ");
}

export default function AdminStatusPage() {
  const router = useRouter();
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canAccess = canAccessAdministration(authQuery.data);
  const readinessQuery = useQuery({
    queryKey: ["readiness"],
    queryFn: api.getReadiness,
    enabled: canAccess,
    retry: false,
    refetchInterval: 30_000,
  });
  const versionQuery = useQuery({
    queryKey: ["version"],
    queryFn: api.getVersion,
    enabled: canAccess,
    staleTime: Infinity,
  });
  const aiQuery = useQuery({
    queryKey: ["ai-task-status", "all", "", 0, 1],
    queryFn: () => api.getAIStatus({ limit: 1 }),
    enabled: canAccess,
    retry: false,
    refetchInterval: 10_000,
  });
  const syncQuery = useQuery({
    queryKey: ["sync-status"],
    queryFn: api.getSyncStatus,
    enabled: canAccess,
    retry: false,
    refetchInterval: 15_000,
  });
  const retrievalQuery = useQuery({
    queryKey: ["ticket-intelligence-status"],
    queryFn: api.getTicketIntelligenceStatus,
    enabled: canAccess,
    retry: false,
    refetchInterval: 30_000,
  });
  const oauthQuery = useQuery({
    queryKey: ["oauth-status"],
    queryFn: api.getOAuthStatus,
    enabled: canAccess,
    retry: false,
    refetchInterval: 30_000,
  });

  const operationalQueries = [readinessQuery, aiQuery, syncQuery, retrievalQuery, oauthQuery];
  const authError = isAuthError(authQuery.error) || operationalQueries.some((query) => isAuthError(query.error));
  useEffect(() => {
    if (authError) router.replace("/login?next=/settings/status");
  }, [authError, router]);

  if (authQuery.isLoading) return <StatusSkeleton />;
  if (authError) return null;
  if (!canAccess) {
    return (
      <PageFrame>
        <ErrorState title="Administrator access required" description="Workspace-wide operational status is available only to active administrators." />
      </PageFrame>
    );
  }

  const ai = aiQuery.data;
  const sync = syncQuery.data;
  const retrieval = retrievalQuery.data;
  const oauth = oauthQuery.data;
  const version = versionQuery.data;
  const syncNeedsReview = Boolean(
    sync?.last_status === "error"
    || sync?.last_status === "throttled"
    || sync?.attachment_errors
    || (!sync?.attachment_storage_configured && sync?.attachment_pending)
  );
  const unavailableCount = operationalQueries.filter((query) => query.error).length;
  const warningCount = [
    Boolean(ai?.queue.attention),
    syncNeedsReview,
    Boolean(retrieval?.rag_v2.dead_letter || retrieval?.rag_v2.indexing_errors),
    Boolean(oauth?.configured && !oauth.connected),
    readinessQuery.data?.status === "not_ready",
  ].filter(Boolean).length;
  const refreshing = operationalQueries.some((query) => query.isFetching);
  const refreshAll = () => {
    void Promise.all(operationalQueries.map((query) => query.refetch()));
  };
  const lastSnapshot = ai?.generated_at || sync?.run_finished_at || version?.build_time || null;

  return (
    <PageFrame width="wide" className="space-y-8">
      <PageHeader
        eyebrow="Admin"
        icon={<Activity className="h-5 w-5" />}
        title="Status"
        description="A single operational view for application readiness, AI tasks, ticket synchronization, search indexing, and integration connectivity."
        meta={`Live checks refresh independently${lastSnapshot ? ` · latest snapshot ${formatTimeAgo(lastSnapshot)}` : ""}`}
        actions={(
          <div className="flex gap-2">
            <Link href="/settings" className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-linen-500 bg-linen-50 px-4 text-sm font-semibold text-ink-700 shadow-sm hover:bg-linen-200">
              <ArrowLeft className="h-4 w-4" /> Settings
            </Link>
            <Button variant="secondary" onClick={refreshAll} pending={refreshing} pendingLabel="Refreshing…" leadingIcon={<RefreshCw className="h-4 w-4" />}>Refresh all</Button>
          </div>
        )}
      />

      {unavailableCount > 0 && (
        <Alert variant="danger" title={`${unavailableCount} status check${unavailableCount === 1 ? " is" : "s are"} unavailable`}>
          Available checks are still shown below. Refresh to retry without changing any operational state.
        </Alert>
      )}
      {warningCount > 0 && unavailableCount === 0 && (
        <Alert variant="warning" title={`${warningCount} area${warningCount === 1 ? " needs" : "s need"} review`}>
          Open the affected status card for queue, retry, provider, or indexing detail.
        </Alert>
      )}

      <SummaryStrip label="Admin status overview">
        <SummaryMetric label="Checks" value="5" detail="Independent operational areas" icon={<Activity className="h-4 w-4" />} />
        <SummaryMetric label="Needs review" value={warningCount.toLocaleString()} detail="Degraded but still observable" icon={<TriangleAlert className="h-4 w-4" />} />
        <SummaryMetric label="Unavailable" value={unavailableCount.toLocaleString()} detail="Checks that could not respond" icon={<Cloud className="h-4 w-4" />} />
        <SummaryMetric label="Build" value={version?.version || "Loading…"} detail={version?.build_sha ? `Commit ${version.build_sha.slice(0, 12)}` : "Deployment identity pending"} icon={<Server className="h-4 w-4" />} />
      </SummaryStrip>

      <section aria-labelledby="operational-status-heading">
        <div id="operational-status-heading"><SectionHeader title="Operational systems" description="Each card reports its own source and refresh cadence so one unavailable dependency does not hide the others." /></div>
        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          <StatusCard
            icon={<Server className="h-5 w-5" />}
            title="Application readiness"
            tone={readinessQuery.error ? "unavailable" : readinessQuery.data?.status === "ready" ? "healthy" : readinessQuery.data ? "warning" : "neutral"}
            status={readinessQuery.error ? "Unavailable" : readinessQuery.data?.status === "ready" ? "Ready" : readinessQuery.data ? "Not ready" : "Checking…"}
            description="Backend readiness and its required database dependency."
            facts={[
              { label: "Database", value: readinessQuery.data?.checks.database || "Checking…" },
              { label: "Version", value: version?.version || "Loading…" },
              { label: "Build time", value: version?.build_time ? new Date(version.build_time).toLocaleString() : "Not recorded" },
            ]}
            diagnosticArea="application"
          />
          <StatusCard
            icon={<Bot className="h-5 w-5" />}
            title="AI operations"
            tone={aiQuery.error ? "unavailable" : ai?.queue.attention ? "warning" : ai ? "healthy" : "neutral"}
            status={aiQuery.error ? "Unavailable" : ai?.queue.attention ? "Needs attention" : ai ? "Healthy" : "Checking…"}
            description="Durable ticket-analysis queue, worker leases, retries, and provider calls."
            facts={[
              { label: "Active tasks", value: ai ? String(ai.queue.queued + ai.queue.running) : "—" },
              { label: "Needs attention", value: ai ? String(ai.queue.attention) : "—" },
              { label: "Provider calls · 24h", value: ai ? String(ai.calls_24h.calls) : "—" },
            ]}
            href="/settings/status/ai"
            action="Open AI status"
            diagnosticArea="ai"
          />
          <StatusCard
            icon={<RefreshCw className="h-5 w-5" />}
            title="Ticket synchronization"
            tone={syncQuery.error ? "unavailable" : syncNeedsReview ? "warning" : syncTone(sync?.last_status)}
            status={syncQuery.error ? "Unavailable" : syncNeedsReview ? "Needs attention" : syncLabel(sync?.last_status)}
            description="Freshservice current, historical, conversation, attachment, and API-budget lanes."
            facts={[
              { label: "Provider", value: sync?.provider || "Not configured" },
              { label: "Last sync", value: sync?.last_synced_at ? formatTimeAgo(sync.last_synced_at) : "Not yet" },
              { label: "Attachments", value: sync ? `${sync.attachment_stored.toLocaleString()} stored · ${sync.attachment_pending.toLocaleString()} pending` : "—" },
            ]}
            href="/settings/status/sync"
            action="Open sync status"
            diagnosticArea="sync"
          />
          <StatusCard
            icon={<Database className="h-5 w-5" />}
            title="Search and retrieval"
            tone={
              retrievalQuery.error
                ? "unavailable"
                : retrieval?.rag_v2.dead_letter || retrieval?.rag_v2.indexing_errors
                  ? "warning"
                  : retrieval?.vector_store_ready
                    ? "healthy"
                    : retrieval
                      ? "neutral"
                      : "neutral"
            }
            status={retrievalQuery.error ? "Unavailable" : retrieval?.rag_v2.dead_letter || retrieval?.rag_v2.indexing_errors ? "Needs attention" : retrieval?.vector_store_ready ? "Ready" : retrieval ? "Not enabled" : "Checking…"}
            description="Ticket search documents, embeddings, and the RAG v2 indexing worker."
            facts={[
              { label: "Embedded documents", value: retrieval ? retrieval.embedded_documents.toLocaleString() : "—" },
              { label: "Queued chunks", value: retrieval ? retrieval.rag_v2.queued.toLocaleString() : "—" },
              { label: "Index errors", value: retrieval ? retrieval.rag_v2.indexing_errors.toLocaleString() : "—" },
            ]}
            href="/settings#settings-ai"
            action="Open AI configuration"
            diagnosticArea="retrieval"
          />
          <StatusCard
            icon={<KeyRound className="h-5 w-5" />}
            title="Freshservice authentication"
            tone={oauthQuery.error ? "unavailable" : oauth?.connected ? "healthy" : oauth?.configured ? "warning" : oauth ? "neutral" : "neutral"}
            status={oauthQuery.error ? "Unavailable" : oauth?.connected ? "Connected" : oauth?.configured ? "Authorization required" : oauth ? "Not configured" : "Checking…"}
            description="Server-side OAuth configuration and current connection state."
            facts={[
              { label: "OAuth app", value: oauth?.configured ? "Configured" : "Not configured" },
              { label: "Connection", value: oauth?.connected ? "Connected" : "Disconnected" },
              { label: "Account", value: oauth?.domain || "Not selected" },
            ]}
            href="/settings#settings-ticketing"
            action="Open integration settings"
            diagnosticArea="oauth"
          />
        </div>
      </section>

      <ContentSurface className="p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <HardDrive className="mt-0.5 h-5 w-5 shrink-0 text-semantic-primary" />
          <div>
            <h2 className="text-sm font-semibold text-ink-700">Status checks are read-only</h2>
            <p className="mt-1 text-xs leading-5 text-ink-500">Refreshing this page reads durable counters and health endpoints. It does not start synchronization, retry AI work, update settings, or contact an AI model.</p>
          </div>
        </div>
      </ContentSurface>
    </PageFrame>
  );
}

function StatusCard({
  icon,
  title,
  tone,
  status,
  description,
  facts,
  href,
  action,
  diagnosticArea,
}: {
  icon: React.ReactNode;
  title: string;
  tone: StatusTone;
  status: string;
  description: string;
  facts: Array<{ label: string; value: string }>;
  href?: string;
  action?: string;
  diagnosticArea?: OperationalDiagnosticArea;
}) {
  const presentation = {
    healthy: { badge: "success" as const, icon: "bg-[var(--color-success-soft)] text-semantic-success" },
    active: { badge: "info" as const, icon: "bg-[var(--color-info-soft)] text-semantic-info" },
    warning: { badge: "warning" as const, icon: "bg-[var(--color-warning-soft)] text-semantic-warning" },
    neutral: { badge: "neutral" as const, icon: "bg-linen-300 text-ink-500" },
    unavailable: { badge: "danger" as const, icon: "bg-[var(--color-danger-soft)] text-semantic-danger" },
  }[tone];
  return (
    <ContentSurface className="flex min-h-64 flex-col p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <span className={`grid h-10 w-10 place-items-center rounded-xl ${presentation.icon}`} aria-hidden="true">{icon}</span>
        <Badge variant={presentation.badge} dot>{status}</Badge>
      </div>
      <h2 className="mt-4 text-base font-semibold text-ink-700">{title}</h2>
      <p className="mt-1 text-xs leading-5 text-ink-500">{description}</p>
      <dl className="mt-5 grid grid-cols-3 gap-3 border-t border-linen-300 pt-4">
        {facts.map((fact) => (
          <div key={fact.label} className="min-w-0">
            <dt className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-400">{fact.label}</dt>
            <dd className="mt-1 break-words text-xs font-medium text-ink-600">{fact.value}</dd>
          </div>
        ))}
      </dl>
      {diagnosticArea && (tone === "warning" || tone === "unavailable") && (
        <DiagnosticReveal area={diagnosticArea} className="mt-4" />
      )}
      {href && action && (
        <div className="mt-auto pt-5 text-right">
          <Link href={href} className="text-xs font-semibold text-semantic-primary hover:underline">{action} →</Link>
        </div>
      )}
    </ContentSurface>
  );
}

function SummaryMetric({ label, value, detail, icon }: { label: string; value: string; detail: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">{icon}{label}</div>
      <p className="mt-3 text-2xl font-semibold tracking-[-0.035em] text-ink-700">{value}</p>
      <p className="mt-1 text-xs leading-5 text-ink-500">{detail}</p>
    </div>
  );
}

function StatusSkeleton() {
  return (
    <PageFrame width="wide" aria-busy="true" aria-label="Loading admin status">
      <div className="space-y-3 border-b border-linen-400 pb-6"><Skeleton className="h-3 w-24" /><Skeleton className="h-10 w-56" /><Skeleton className="h-4 w-full max-w-2xl" /></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-32" rounded="lg" />)}</div>
      <div className="grid gap-4 xl:grid-cols-2">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-64" rounded="lg" />)}</div>
    </PageFrame>
  );
}
