"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, MessageSquareHeart, Send, Star } from "lucide-react";
import { Alert, Badge, Button, Dialog, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { SurveyTemplate, Ticket } from "@/lib/types";

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

export default function SurveysPage() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [notice, setNotice] = useState(false);
  const statsQuery = useQuery({ queryKey: ["surveyStats"], queryFn: api.getSurveyStats });
  const surveysQuery = useQuery({ queryKey: ["surveys"], queryFn: api.getSurveys });
  const templatesQuery = useQuery({ queryKey: ["surveyTemplates"], queryFn: api.getSurveyTemplates });
  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: api.getTickets });
  const sendMutation = useMutation({
    mutationFn: ({ ticketId, templateId }: { ticketId: string; templateId: number }) => api.sendSurvey(ticketId, templateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["surveys"] });
      void queryClient.invalidateQueries({ queryKey: ["surveyStats"] });
      setFormOpen(false);
      setNotice(true);
    },
  });
  const stats = statsQuery.data;
  const distribution = stats?.distribution ?? {};
  const distributionTotal = Object.values(distribution).reduce((sum, count) => sum + count, 0);
  const surveys = surveysQuery.data ?? [];

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-col gap-4 border-b border-linen-400 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-400">Experience signals</p><h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-ink-700">Surveys</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-ink-500">Measure satisfaction after service delivery and monitor response quality over time.</p></div>
        <Button leadingIcon={<Send className="h-4 w-4" />} onClick={() => { sendMutation.reset(); setFormOpen(true); }}>Send survey</Button>
      </header>
      {notice && <Alert variant="success" title="Survey sent" action={<Button size="sm" variant="ghost" onClick={() => setNotice(false)}>Dismiss</Button>}>The request is now included in delivery and response reporting.</Alert>}

      <section aria-label="Survey performance" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Total sent" value={stats ? stats.total_sent.toLocaleString() : "—"} detail="All delivery attempts" loading={statsQuery.isLoading} />
        <Metric label="Response rate" value={stats ? `${stats.response_rate}%` : "—"} detail="Completed of sent" loading={statsQuery.isLoading} />
        <Metric label="Average rating" value={stats ? stats.avg_rating.toFixed(1) : "—"} detail="Five-point scale" loading={statsQuery.isLoading} />
        <Metric label="Responses" value={stats ? stats.responded.toLocaleString() : "—"} detail="Feedback received" loading={statsQuery.isLoading} />
      </section>
      {statsQuery.isError && <Alert variant="warning" title="Survey summary unavailable">The delivery ledger remains available below.</Alert>}

      {stats && distributionTotal > 0 && <section className="grid gap-6 rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:grid-cols-[11rem_1fr] sm:p-6" aria-labelledby="rating-distribution-title"><div className="flex flex-col justify-center rounded-xl bg-ink-700 p-5 text-white"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-white/60">CSAT score</p><p className="mt-3 text-5xl font-semibold tracking-[-0.06em] tabular-nums">{stats.avg_rating.toFixed(1)}</p><div className="mt-3 flex gap-1" aria-label={`${stats.avg_rating.toFixed(1)} out of 5 stars`}>{[1,2,3,4,5].map((value) => <Star key={value} className={`h-4 w-4 ${value <= Math.round(stats.avg_rating) ? "fill-amber-400 text-amber-400" : "text-white/30"}`} aria-hidden="true" />)}</div><p className="mt-3 text-xs text-white/60">{distributionTotal} rated responses</p></div><div><div className="flex items-center gap-2"><BarChart3 className="h-4 w-4 text-ink-400" aria-hidden="true" /><h2 id="rating-distribution-title" className="text-sm font-semibold text-ink-700">Rating distribution</h2></div><div className="mt-5 space-y-3">{[5,4,3,2,1].map((rating) => { const count = distribution[String(rating)] ?? 0; const percentage = distributionTotal ? Math.round((count / distributionTotal) * 100) : 0; return <div key={rating} className="grid grid-cols-[2.5rem_1fr_3.5rem] items-center gap-3 text-xs"><span className="font-medium text-ink-600">{rating} star</span><div className="h-2.5 overflow-hidden rounded-full bg-linen-300" role="progressbar" aria-label={`${rating} star responses`} aria-valuenow={percentage} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-amber-400" style={{ width: `${percentage}%` }} /></div><span className="text-right tabular-nums text-ink-500">{count} · {percentage}%</span></div>; })}</div></div></section>}

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
        <div className="border-b border-linen-400 p-4"><h2 className="text-sm font-semibold text-ink-700">Delivery ledger</h2><p className="mt-1 text-xs text-ink-500">{surveys.length} survey request{surveys.length === 1 ? "" : "s"}</p></div>
        {surveysQuery.isLoading ? <div className="space-y-3 p-5" aria-label="Loading survey ledger">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-14 w-full" />)}</div> : surveysQuery.isError ? <ErrorState className="m-5" title="The survey ledger could not be loaded" description="No records were changed. Retry the request to restore the delivery view." onRetry={() => void surveysQuery.refetch()} retrying={surveysQuery.isFetching} /> : surveys.length === 0 ? <EmptyState className="m-5" icon={<MessageSquareHeart className="h-5 w-5" />} title="No surveys sent yet" description="Send a survey after resolving a ticket to begin measuring customer satisfaction." action={<Button onClick={() => setFormOpen(true)}>Send survey</Button>} /> : <>
          <div className="divide-y divide-linen-300 md:hidden">{surveys.map((survey) => <article key={survey.id} className="p-4"><div className="flex items-start justify-between gap-3"><p className="min-w-0 truncate text-sm font-semibold text-ink-700">{survey.ticket_subject || survey.ticket_id}</p><Badge variant={survey.responded_at ? "success" : "warning"} dot>{survey.responded_at ? "Responded" : "Awaiting response"}</Badge></div><dl className="mt-3 grid grid-cols-2 gap-3 text-xs"><div><dt className="text-ink-400">Sent</dt><dd className="mt-1 text-ink-600">{formatDate(survey.sent_at)}</dd></div><div><dt className="text-ink-400">Responded</dt><dd className="mt-1 text-ink-600">{formatDate(survey.responded_at)}</dd></div></dl></article>)}</div>
          <div className="hidden overflow-x-auto md:block"><table className="w-full text-sm"><thead className="bg-linen-100 text-left text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400"><tr><th scope="col" className="px-5 py-3">Ticket</th><th scope="col" className="px-4 py-3">Sent</th><th scope="col" className="px-4 py-3">Responded</th><th scope="col" className="px-5 py-3">Status</th></tr></thead><tbody className="divide-y divide-linen-300">{surveys.map((survey) => <tr key={survey.id} className="hover:bg-linen-100"><td className="max-w-sm px-5 py-4 font-semibold text-ink-700"><span className="block truncate">{survey.ticket_subject || survey.ticket_id}</span></td><td className="px-4 py-4 text-xs text-ink-500">{formatDate(survey.sent_at)}</td><td className="px-4 py-4 text-xs text-ink-500">{formatDate(survey.responded_at)}</td><td className="px-5 py-4"><Badge variant={survey.responded_at ? "success" : "warning"} dot>{survey.responded_at ? "Responded" : "Awaiting response"}</Badge></td></tr>)}</tbody></table></div>
        </>}
      </section>
      <SendSurveyDialog open={formOpen} tickets={ticketsQuery.data ?? []} templates={templatesQuery.data ?? []} dependenciesLoading={ticketsQuery.isLoading || templatesQuery.isLoading} dependenciesError={ticketsQuery.isError || templatesQuery.isError} onOpenChange={(open) => { if (!open) sendMutation.reset(); setFormOpen(open); }} onSubmit={(ticketId, templateId) => sendMutation.mutate({ ticketId, templateId })} pending={sendMutation.isPending} error={sendMutation.error} />
    </div>
  );
}

function Metric({ label, value, detail, loading }: { label: string; value: string; detail: string; loading: boolean }) { return <div className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5"><p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</p>{loading ? <><Skeleton className="mt-4 h-8 w-20" /><Skeleton className="mt-3 h-3 w-28" /></> : <><p className="mt-3 text-3xl font-semibold tracking-[-0.04em] tabular-nums text-ink-700">{value}</p><p className="mt-1 text-xs leading-5 text-ink-500">{detail}</p></>}</div>; }

function SendSurveyDialog({ open, tickets, templates, dependenciesLoading, dependenciesError, onOpenChange, onSubmit, pending, error }: { open: boolean; tickets: Ticket[]; templates: SurveyTemplate[]; dependenciesLoading: boolean; dependenciesError: boolean; onOpenChange: (open: boolean) => void; onSubmit: (ticketId: string, templateId: number) => void; pending: boolean; error: unknown }) {
  const [ticketId, setTicketId] = useState(""); const [templateId, setTemplateId] = useState(""); const activeTemplates = templates.filter((template) => template.is_active); const selectedTemplate = activeTemplates.find((template) => String(template.id) === templateId);
  const errorMessage = error instanceof Error ? error.message : error ? String(error) : null;
  return <Dialog open={open} onOpenChange={onOpenChange} title="Send survey" description="Choose the completed service interaction and the feedback prompt recipients will receive." dismissible={!pending} closeOnBackdrop={!pending} footer={<><Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button><Button leadingIcon={<Send className="h-4 w-4" />} onClick={() => onSubmit(ticketId, Number(templateId))} pending={pending} pendingLabel="Sending…" disabled={!ticketId || !templateId || dependenciesLoading || dependenciesError}>Send survey</Button></>}><div className="space-y-4">{errorMessage && <Alert variant="danger" title="Survey was not sent">{errorMessage}</Alert>}{dependenciesError && <Alert variant="danger" title="Survey options are unavailable">Close this dialog and retry after tickets and templates are available.</Alert>}<label className="block"><span className="text-sm font-medium text-ink-700">Ticket <span className="text-semantic-danger">*</span></span><select className="input-base mt-2 w-full" value={ticketId} onChange={(event) => setTicketId(event.target.value)} disabled={dependenciesLoading || dependenciesError}><option value="">{dependenciesLoading ? "Loading tickets…" : "Select a ticket"}</option>{tickets.map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.subject}</option>)}</select></label><label className="block"><span className="text-sm font-medium text-ink-700">Template <span className="text-semantic-danger">*</span></span><select className="input-base mt-2 w-full" value={templateId} onChange={(event) => setTemplateId(event.target.value)} disabled={dependenciesLoading || dependenciesError}><option value="">Select a template</option>{activeTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label>{selectedTemplate && <div className="rounded-xl border border-linen-400 bg-linen-100 p-4"><p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">Recipient prompt</p><p className="mt-2 text-sm leading-6 text-ink-700">{selectedTemplate.question}</p></div>}</div></Dialog>;
}
