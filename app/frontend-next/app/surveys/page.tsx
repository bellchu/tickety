"use client";

import { useEffect, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, MessageSquareHeart, Send, Star } from "lucide-react";
import { Alert, Badge, Button, DataListCard, DataTable, DataTableViewport, Dialog, EmptyState, ErrorState, ListText, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { canManageOperationalRecords } from "@/lib/auth";
import { formatLocalDateTime } from "@/lib/date-time";
import type { SurveyOut, SurveyTemplate, Ticket } from "@/lib/types";
import { PageFrame, PageHeader, SummaryStrip } from "@/components/layout/PageLayout";

function formatDate(value: string | null) {
  return formatLocalDateTime(value, { dateStyle: "medium" }, "—");
}

export default function SurveysPage() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [notice, setNotice] = useState(false);
  const [ticketSearch, setTicketSearch] = useState("");
  const [debouncedTicketSearch, setDebouncedTicketSearch] = useState("");
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManage = !authQuery.isError && canManageOperationalRecords(authQuery.data);
  const statsQuery = useQuery({ queryKey: ["surveyStats"], queryFn: api.getSurveyStats, enabled: canManage });
  const surveysQuery = useInfiniteQuery({
    queryKey: ["surveys"],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getSurveysPage({ limit: 50, offset: pageParam }),
    getNextPageParam: (lastPage) => lastPage.hasMore ? lastPage.offset + lastPage.limit : undefined,
    enabled: canManage,
  });
  const templatesQuery = useQuery({ queryKey: ["surveyTemplates"], queryFn: api.getSurveyTemplates, enabled: canManage });
  const emailStatusQuery = useQuery({ queryKey: ["email-status"], queryFn: api.getEmailStatus, enabled: canManage, retry: false });
  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedTicketSearch(ticketSearch.trim()),
      300,
    );
    return () => window.clearTimeout(timer);
  }, [ticketSearch]);
  const ticketsQuery = useQuery({
    queryKey: ["survey-ticket-options", debouncedTicketSearch],
    queryFn: () => api.getSurveyEligibleTickets({
      search: debouncedTicketSearch || undefined,
      limit: 50,
    }),
    enabled: canManage && formOpen,
  });
  const sendMutation = useMutation({
    mutationFn: ({ ticketId, templateId }: { ticketId: string; templateId: number }) => api.sendSurvey(ticketId, templateId),
    onSuccess: () => {
      setFormOpen(false);
      setNotice(true);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["surveys"] });
      void queryClient.invalidateQueries({ queryKey: ["surveyStats"] });
    },
  });
  const stats = statsQuery.data;
  const distribution = stats?.distribution ?? {};
  const distributionTotal = Object.values(distribution).reduce((sum, count) => sum + count, 0);
  const surveys = surveysQuery.data?.pages.flatMap((page) => page.surveys) ?? [];
  const hasActiveTemplate = Boolean(templatesQuery.data?.some((template) => template.is_active));

  if (authQuery.isLoading) {
    return <PageFrame><div className="space-y-4" aria-label="Checking survey access" aria-busy="true"><Skeleton className="h-10 w-56" /><Skeleton className="h-72 w-full" /></div></PageFrame>;
  }
  if (!canManage) {
    return <PageFrame><ErrorState title="Survey operations are restricted" description="An active administrator or supervisor session is required to view recipients, delivery records, and send surveys." onRetry={() => void authQuery.refetch()} retrying={authQuery.isFetching} /></PageFrame>;
  }

  return (
    <PageFrame>
      <PageHeader eyebrow="Experience signals" icon={<MessageSquareHeart className="h-4 w-4" />} title="Surveys" description="Measure satisfaction after service delivery and monitor response quality over time." actions={<Button leadingIcon={<Send className="h-4 w-4" />} onClick={() => { sendMutation.reset(); setFormOpen(true); }}>Send survey</Button>} />
      {notice && <Alert variant="success" title="Delivery accepted" action={<Button size="sm" variant="ghost" onClick={() => setNotice(false)}>Dismiss</Button>}>SendGrid accepted the survey message. Inbox delivery is not guaranteed; the ledger records the provider acceptance separately from the response.</Alert>}
      {templatesQuery.isSuccess && !hasActiveTemplate && <Alert variant="warning" title="Active survey template required">No active feedback prompt is available. An administrator must restore or activate a template before a survey can be sent.</Alert>}
      {emailStatusQuery.data && !emailStatusQuery.data.configured && <Alert variant="warning" title="Email delivery is not configured">Survey sending remains unavailable until SendGrid is configured in system settings.</Alert>}
      {emailStatusQuery.isError && <Alert variant="warning" title="Email readiness unavailable">Survey delivery stays disabled until the email provider status can be verified.</Alert>}

      <SummaryStrip label="Survey performance" className="grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
        <Metric label="Total sent" value={stats ? stats.total_sent.toLocaleString() : "—"} detail="Provider-accepted deliveries" loading={statsQuery.isLoading} />
        <Metric label="Response rate" value={stats?.response_rate != null ? `${stats.response_rate}%` : "No data"} detail="Completed of sent" loading={statsQuery.isLoading} />
        <Metric label="Average rating" value={stats?.avg_rating != null ? stats.avg_rating.toFixed(1) : "No data"} detail="Five-point scale" loading={statsQuery.isLoading} />
      </SummaryStrip>
      {statsQuery.isError && <Alert variant="warning" title="Survey summary unavailable">The delivery ledger remains available below.</Alert>}

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm" aria-labelledby="delivery-ledger-title">
        <div className="border-b border-linen-400 p-4"><h2 id="delivery-ledger-title" className="text-sm font-semibold text-ink-700">Delivery ledger</h2><p className="mt-1 text-xs text-ink-500">{surveys.length} survey request{surveys.length === 1 ? "" : "s"}</p></div>
        {surveysQuery.isLoading ? <div className="space-y-3 p-5" aria-label="Loading survey ledger">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-14 w-full" />)}</div> : surveysQuery.isError && !surveys.length ? <ErrorState className="m-5" title="The survey ledger could not be loaded" description="No records were changed. Retry the request to restore the delivery view." onRetry={() => void surveysQuery.refetch()} retrying={surveysQuery.isFetching} /> : surveys.length === 0 ? <EmptyState className="m-5" icon={<MessageSquareHeart className="h-5 w-5" />} title="No surveys sent yet" description="Send a survey after resolving a ticket to begin measuring customer satisfaction." action={<Button onClick={() => setFormOpen(true)}>Send survey</Button>} /> : <>
          <div className="grid gap-3 bg-linen-100/60 p-3 md:hidden">{surveys.map((survey) => { const status = surveyDeliveryStatus(survey); return <DataListCard key={survey.id}><div className="flex min-w-0 items-start justify-between gap-3"><ListText text={survey.ticket_subject || survey.ticket_id} lines={2} className="flex-1 text-sm font-semibold leading-5 text-ink-700" /><Badge className="shrink-0" variant={status.variant} dot>{status.label}</Badge></div><dl className="mt-4 grid grid-cols-2 gap-3 border-t border-linen-300 pt-3 text-xs"><div><dt className="text-ink-400">Delivery accepted</dt><dd className="mt-1 text-ink-600">{formatDate(survey.sent_at)}</dd></div><div><dt className="text-ink-400">Responded</dt><dd className="mt-1 text-ink-600">{formatDate(survey.responded_at)}</dd></div></dl></DataListCard>; })}</div>
          <DataTableViewport label="Survey delivery ledger" className="hidden md:block"><DataTable><colgroup><col className="w-[46%]" /><col className="w-[18%]" /><col className="w-[18%]" /><col className="w-[18%]" /></colgroup><thead className="bg-linen-100 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400"><tr><th scope="col" className="px-5 py-3">Ticket</th><th scope="col" className="px-4 py-3">Delivery accepted</th><th scope="col" className="px-4 py-3">Responded</th><th scope="col" className="px-5 py-3">Status</th></tr></thead><tbody className="divide-y divide-linen-300">{surveys.map((survey) => { const status = surveyDeliveryStatus(survey); return <tr key={survey.id} className="hover:bg-linen-100"><td className="px-5 py-4"><ListText text={survey.ticket_subject || survey.ticket_id} lines={2} className="font-semibold leading-5 text-ink-700" /></td><td className="px-4 py-4 text-xs text-ink-500">{formatDate(survey.sent_at)}</td><td className="px-4 py-4 text-xs text-ink-500">{formatDate(survey.responded_at)}</td><td className="px-5 py-4"><Badge variant={status.variant} dot>{status.label}</Badge></td></tr>; })}</tbody></DataTable></DataTableViewport>
          {surveysQuery.isFetchNextPageError && <div className="border-t border-linen-300 p-4"><Alert variant="danger" title="More deliveries could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void surveysQuery.fetchNextPage()}>Retry</Button>}>The delivery records already shown remain available.</Alert></div>}
          {surveysQuery.hasNextPage && !surveysQuery.isFetchNextPageError && <div className="flex justify-center border-t border-linen-300 p-4"><Button variant="secondary" onClick={() => void surveysQuery.fetchNextPage()} pending={surveysQuery.isFetchingNextPage} pendingLabel="Loading…">Load more deliveries</Button></div>}
        </>}
      </section>

      {stats?.avg_rating != null && distributionTotal > 0 && <section className="grid min-w-0 gap-6 rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:grid-cols-[11rem_minmax(0,1fr)] sm:p-6" aria-labelledby="rating-distribution-title"><div className="flex flex-col justify-center rounded-xl bg-ink-700 p-5 text-white"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-white/60">CSAT score</p><p className="mt-3 break-words text-5xl font-semibold tracking-[-0.06em] tabular-nums [overflow-wrap:anywhere]">{stats.avg_rating.toFixed(1)}</p><div className="mt-3 flex gap-1" aria-label={`${stats.avg_rating.toFixed(1)} out of 5 stars`}>{[1,2,3,4,5].map((value) => <Star key={value} className={`h-4 w-4 ${value <= Math.round(stats.avg_rating!) ? "fill-amber-400 text-amber-400" : "text-white/30"}`} aria-hidden="true" />)}</div><p className="mt-3 text-xs text-white/60">{distributionTotal} rated responses</p></div><div className="min-w-0"><div className="flex items-center gap-2"><BarChart3 className="h-4 w-4 text-ink-400" aria-hidden="true" /><h2 id="rating-distribution-title" className="text-sm font-semibold text-ink-700">Rating distribution</h2></div><div className="mt-5 space-y-3">{[5,4,3,2,1].map((rating) => { const count = distribution[String(rating)] ?? 0; const percentage = distributionTotal ? Math.round((count / distributionTotal) * 100) : 0; return <div key={rating} className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 text-xs"><span className="font-medium text-ink-600">{rating} star</span><div className="h-2.5 overflow-hidden rounded-full bg-linen-300" role="progressbar" aria-label={`${rating} star responses`} aria-valuenow={percentage} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-amber-400" style={{ width: `${percentage}%` }} /></div><span className="text-right tabular-nums text-ink-500">{count.toLocaleString()} · {percentage}%</span></div>; })}</div></div></section>}
      <SendSurveyDialog key={formOpen ? "open" : "closed"} open={formOpen} tickets={ticketsQuery.data?.tickets ?? []} ticketSearch={ticketSearch} ticketHasMore={ticketsQuery.data?.hasMore ?? false} onTicketSearchChange={setTicketSearch} templates={templatesQuery.data ?? []} emailConfigured={emailStatusQuery.data?.configured === true} dependenciesLoading={ticketsQuery.isLoading || templatesQuery.isLoading || emailStatusQuery.isLoading} dependenciesError={ticketsQuery.isError || templatesQuery.isError || emailStatusQuery.isError} dependenciesRetrying={ticketsQuery.isFetching || templatesQuery.isFetching || emailStatusQuery.isFetching} onRetryDependencies={() => { void ticketsQuery.refetch(); void templatesQuery.refetch(); void emailStatusQuery.refetch(); }} onOpenChange={(open) => { if (!open) { sendMutation.reset(); setTicketSearch(""); } setFormOpen(open); }} onSubmit={(ticketId, templateId) => sendMutation.mutate({ ticketId, templateId })} pending={sendMutation.isPending} error={sendMutation.error} />
    </PageFrame>
  );
}

function Metric({ label, value, detail, loading }: { label: string; value: string; detail: string; loading: boolean }) { return <div className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5"><p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</p>{loading ? <><Skeleton className="mt-4 h-8 w-20" /><Skeleton className="mt-3 h-3 w-28" /></> : <><p className="mt-3 text-3xl font-semibold tracking-[-0.04em] tabular-nums text-ink-700">{value}</p><p className="mt-1 text-xs leading-5 text-ink-500">{detail}</p></>}</div>; }

function surveyDeliveryStatus(survey: SurveyOut): { label: string; variant: "neutral" | "info" | "success" | "warning" | "danger" } {
  if (survey.delivery_status === "failed") return { label: "Delivery failed", variant: "danger" };
  if (survey.delivery_status === "uncertain") return { label: "Delivery unconfirmed", variant: "warning" };
  if (survey.delivery_status === "pending") return { label: "Provider pending", variant: "info" };
  if (survey.delivery_status === "legacy") return { label: "Legacy record", variant: "neutral" };
  if (survey.responded_at) return { label: "Responded", variant: "success" };
  return { label: "Awaiting response", variant: "warning" };
}

function SendSurveyDialog({ open, tickets, ticketSearch, ticketHasMore, onTicketSearchChange, templates, emailConfigured, dependenciesLoading, dependenciesError, dependenciesRetrying, onRetryDependencies, onOpenChange, onSubmit, pending, error }: { open: boolean; tickets: Ticket[]; ticketSearch: string; ticketHasMore: boolean; onTicketSearchChange: (value: string) => void; templates: SurveyTemplate[]; emailConfigured: boolean; dependenciesLoading: boolean; dependenciesError: boolean; dependenciesRetrying: boolean; onRetryDependencies: () => void; onOpenChange: (open: boolean) => void; onSubmit: (ticketId: string, templateId: number) => void; pending: boolean; error: unknown }) {
  const [ticketId, setTicketId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const activeTemplates = templates.filter((template) => template.is_active);
  const selectedTemplate = activeTemplates.find((template) => String(template.id) === templateId);
  const errorMessage = error instanceof Error ? error.message : error ? String(error) : null;
  return <Dialog open={open} onOpenChange={onOpenChange} title="Send survey" description="Choose the completed service interaction and the feedback prompt recipients will receive." dismissible={!pending} closeOnBackdrop={!pending} footer={<><Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button><Button leadingIcon={<Send className="h-4 w-4" />} onClick={() => onSubmit(ticketId, Number(templateId))} pending={pending} pendingLabel="Sending…" disabled={!ticketId || !templateId || !emailConfigured || activeTemplates.length === 0 || dependenciesLoading || dependenciesError}>Send survey</Button></>}><div className="space-y-4">{errorMessage && <Alert variant="danger" title="Survey could not be sent">{errorMessage}</Alert>}{dependenciesError && <Alert variant="danger" title="Survey options are unavailable" action={<Button size="sm" variant="ghost" onClick={onRetryDependencies} pending={dependenciesRetrying} pendingLabel="Retrying…">Retry</Button>}>Tickets, templates, and email readiness must all be verified before sending.</Alert>}{!dependenciesLoading && !dependenciesError && activeTemplates.length === 0 && <Alert variant="warning" title="No active survey template">Restore or activate a feedback prompt before sending.</Alert>}{!dependenciesLoading && !dependenciesError && !emailConfigured && <Alert variant="warning" title="Email delivery is not configured">Configure SendGrid before sending a survey.</Alert>}<label className="block"><span className="text-sm font-medium text-ink-700">Find a resolved ticket</span><input className="input-base mt-2 w-full" type="search" maxLength={200} value={ticketSearch} onChange={(event) => { setTicketId(""); onTicketSearchChange(event.target.value); }} placeholder="Search subject, ticket ID, or requester" disabled={dependenciesError} /></label><label className="block"><span className="text-sm font-medium text-ink-700">Ticket <span className="text-semantic-danger">*</span></span><select className="input-base mt-2 w-full" value={ticketId} onChange={(event) => setTicketId(event.target.value)} disabled={dependenciesLoading || dependenciesError || tickets.length === 0}><option value="">{dependenciesLoading ? "Loading tickets…" : tickets.length === 0 ? "No resolved tickets found" : "Select a ticket"}</option>{tickets.map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.subject} · {ticket.id}</option>)}</select>{ticketHasMore && <span className="mt-1 block text-xs text-ink-400">Showing the first 50 matches. Refine the server search to find older tickets.</span>}</label><label className="block"><span className="text-sm font-medium text-ink-700">Template <span className="text-semantic-danger">*</span></span><select className="input-base mt-2 w-full" value={templateId} onChange={(event) => setTemplateId(event.target.value)} disabled={dependenciesLoading || dependenciesError || activeTemplates.length === 0}><option value="">{!dependenciesLoading && activeTemplates.length === 0 ? "No active templates available" : "Select a template"}</option>{activeTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label>{selectedTemplate && <div className="rounded-xl border border-linen-400 bg-linen-100 p-4"><p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">Recipient prompt</p><p className="mt-2 text-sm leading-6 text-ink-700">{selectedTemplate.question}</p></div>}</div></Dialog>;
}
