"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Plus, Ticket as TicketIcon, Timer } from "lucide-react";
import { Alert, Button, DataListCard, DataTable, DataTableViewport, Dialog, EmptyState, ErrorState, ListText, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Ticket } from "@/lib/types";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";

function formatDuration(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (!hours) return `${remainder}m`;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function formatDate(value: string | null) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

export default function TimePage() {
  const queryClient = useQueryClient();
  const [ticketFilter, setTicketFilter] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [notice, setNotice] = useState(false);
  const summaryQuery = useQuery({ queryKey: ["timeSummary"], queryFn: api.getTimeSummary });
  const entriesQuery = useQuery({ queryKey: ["timeEntries", ticketFilter], queryFn: () => api.getTimeEntries(ticketFilter || undefined) });
  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: api.getTickets });
  const createMutation = useMutation({
    mutationFn: ({ ticketId, description, minutes }: { ticketId: string; description: string; minutes: number }) => api.createTimeEntry(ticketId, description, minutes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["timeEntries"] });
      void queryClient.invalidateQueries({ queryKey: ["timeSummary"] });
      setFormOpen(false);
      setNotice(true);
    },
  });
  const entries = useMemo(() => entriesQuery.data ?? [], [entriesQuery.data]);
  const uniqueTicketCount = useMemo(() => new Set(entries.map((entry) => entry.ticket_id)).size, [entries]);
  const average = summaryQuery.data && uniqueTicketCount ? summaryQuery.data.total_hours / uniqueTicketCount : null;

  return (
    <PageFrame>
      <PageHeader eyebrow="Work accounting" icon={<Clock3 className="h-4 w-4" />} title="My time" description="Capture effort against service work and keep delivery records audit-ready." actions={<Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { createMutation.reset(); setFormOpen(true); }}>Log time</Button>} />

      {notice && <Alert variant="success" title="Time entry recorded" action={<Button size="sm" variant="ghost" onClick={() => setNotice(false)}>Dismiss</Button>}>Summaries and ticket totals have been refreshed.</Alert>}

      <section aria-label="Time summary" className="grid gap-3 sm:grid-cols-3">
        <Metric label="Total recorded" value={summaryQuery.data ? `${summaryQuery.data.total_hours.toFixed(1)}h` : "—"} detail="Across the current reporting window" loading={summaryQuery.isLoading} icon={<Timer className="h-4 w-4" />} />
        <Metric label="Today" value={summaryQuery.data ? `${summaryQuery.data.today_hours.toFixed(1)}h` : "—"} detail="Recorded during your local day" loading={summaryQuery.isLoading} icon={<Clock3 className="h-4 w-4" />} />
        <Metric label="Average per ticket" value={average == null ? "—" : `${average.toFixed(1)}h`} detail={uniqueTicketCount ? `Based on ${uniqueTicketCount} ticket${uniqueTicketCount === 1 ? "" : "s"} shown` : "No ticket activity in this view"} loading={summaryQuery.isLoading || entriesQuery.isLoading} icon={<TicketIcon className="h-4 w-4" />} />
      </section>
      {summaryQuery.isError && <Alert variant="warning" title="Summary unavailable">Time entries can still be reviewed and recorded.</Alert>}

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
        <div className="flex flex-col gap-3 border-b border-linen-400 p-4 sm:flex-row sm:items-end sm:justify-between">
          <div><h2 className="text-sm font-semibold text-ink-700">Recorded entries</h2><p className="mt-1 text-xs text-ink-500">{entries.length} entries in the current view</p></div>
          <label className="block w-full sm:w-80"><span className="mb-1.5 block text-xs font-medium text-ink-500">Filter by ticket</span><select className="input-base w-full" value={ticketFilter} onChange={(event) => setTicketFilter(event.target.value)}><option value="">All tickets</option>{(ticketsQuery.data ?? []).map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.subject}</option>)}</select></label>
        </div>
        {entriesQuery.isLoading ? <div className="space-y-3 p-5" aria-label="Loading time entries">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-14 w-full" />)}</div> : entriesQuery.isError ? <ErrorState className="m-5" title="Time entries could not be loaded" description="The current filter was preserved. Try the request again." onRetry={() => void entriesQuery.refetch()} retrying={entriesQuery.isFetching} /> : entries.length === 0 ? <EmptyState className="m-5" icon={<Clock3 className="h-5 w-5" />} title={ticketFilter ? "No time recorded for this ticket" : "No time entries yet"} description={ticketFilter ? "Select another ticket or add the first entry for this work item." : "Log work as it happens to keep reporting accurate."} action={<Button onClick={() => setFormOpen(true)}>Log time</Button>} /> : <>
          <div className="grid gap-3 bg-linen-100/60 p-3 md:hidden">{entries.map((entry) => <DataListCard key={entry.id}><div className="flex min-w-0 items-start justify-between gap-4"><div className="min-w-0 flex-1"><ListText text={entry.description} lines={3} className="text-sm font-semibold leading-5 text-ink-700" /><ListText text={`Ticket ${entry.ticket_id.slice(0, 8)} · ${entry.user_name || entry.user_id}`} lines={2} className="mt-1 text-xs text-ink-500" /></div><span className="shrink-0 text-sm font-semibold tabular-nums text-ink-700">{formatDuration(entry.minutes)}</span></div><p className="mt-3 border-t border-linen-300 pt-3 text-xs text-ink-400">{formatDate(entry.entry_date)}</p></DataListCard>)}</div>
          <DataTableViewport label="Recorded time entries" className="hidden md:block"><DataTable className="min-w-[640px]"><colgroup><col className="w-[46%]" /><col className="w-[24%]" /><col className="w-[14%]" /><col className="w-[16%]" /></colgroup><thead className="bg-linen-100 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400"><tr><th scope="col" className="px-5 py-3">Work item</th><th scope="col" className="px-4 py-3">Contributor</th><th scope="col" className="px-4 py-3 text-right">Duration</th><th scope="col" className="px-5 py-3">Date</th></tr></thead><tbody className="divide-y divide-linen-300">{entries.map((entry) => <tr key={entry.id} className="hover:bg-linen-100"><td className="px-5 py-4"><ListText text={entry.description} lines={2} className="font-medium leading-5 text-ink-700" /><span className="mt-1 block font-mono text-[11px] font-semibold text-ink-400">Ticket {entry.ticket_id.slice(0, 8)}</span></td><td className="px-4 py-4"><ListText text={entry.user_name || entry.user_id} lines={2} className="text-xs text-ink-500" /></td><td className="px-4 py-4 text-right font-semibold tabular-nums text-ink-700">{formatDuration(entry.minutes)}</td><td className="px-5 py-4 text-xs text-ink-500">{formatDate(entry.entry_date)}</td></tr>)}</tbody></DataTable></DataTableViewport>
        </>}
      </section>
      <LogTimeDialog open={formOpen} tickets={ticketsQuery.data ?? []} ticketsLoading={ticketsQuery.isLoading} ticketsError={ticketsQuery.isError} onOpenChange={(open) => { if (!open) createMutation.reset(); setFormOpen(open); }} onSubmit={(ticketId, description, minutes) => createMutation.mutate({ ticketId, description, minutes })} pending={createMutation.isPending} error={createMutation.error} />
    </PageFrame>
  );
}

function Metric({ label, value, detail, icon, loading }: { label: string; value: string; detail: string; icon: React.ReactNode; loading: boolean }) {
  return <div className="rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm"><div className="flex items-start justify-between gap-3"><p className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</p><span className="grid h-8 w-8 place-items-center rounded-lg bg-linen-200 text-ink-500">{icon}</span></div>{loading ? <><Skeleton className="mt-4 h-8 w-20" /><Skeleton className="mt-3 h-3 w-40" /></> : <><p className="mt-3 text-3xl font-semibold tracking-[-0.04em] tabular-nums text-ink-700">{value}</p><p className="mt-1 text-xs leading-5 text-ink-500">{detail}</p></>}</div>;
}

function LogTimeDialog({ open, tickets, ticketsLoading, ticketsError, onOpenChange, onSubmit, pending, error }: { open: boolean; tickets: Ticket[]; ticketsLoading: boolean; ticketsError: boolean; onOpenChange: (open: boolean) => void; onSubmit: (ticketId: string, description: string, minutes: number) => void; pending: boolean; error: unknown }) {
  const [ticketId, setTicketId] = useState("");
  const [description, setDescription] = useState("");
  const [hours, setHours] = useState("");
  const [minutes, setMinutes] = useState("");
  const totalMinutes = (Number.parseInt(hours, 10) || 0) * 60 + (Number.parseInt(minutes, 10) || 0);
  const errorMessage = error instanceof Error ? error.message : error ? String(error) : null;
  return <Dialog open={open} onOpenChange={onOpenChange} title="Log time" description="Record completed effort against a ticket. This entry becomes part of its operational history." dismissible={!pending} closeOnBackdrop={!pending} footer={<><Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button><Button onClick={() => onSubmit(ticketId, description.trim(), totalMinutes)} pending={pending} pendingLabel="Recording…" disabled={!ticketId || !description.trim() || totalMinutes <= 0 || ticketsLoading || ticketsError}>Record time</Button></>}>
    <div className="space-y-4">{errorMessage && <Alert variant="danger" title="Time was not recorded">{errorMessage}</Alert>}{ticketsError && <Alert variant="danger" title="Tickets are unavailable">Close this dialog and retry the ticket list before recording time.</Alert>}<label className="block"><span className="text-sm font-medium text-ink-700">Ticket <span className="text-semantic-danger">*</span></span><select className="input-base mt-2 w-full" value={ticketId} onChange={(event) => setTicketId(event.target.value)} disabled={ticketsLoading || ticketsError}><option value="">{ticketsLoading ? "Loading tickets…" : "Select a ticket"}</option>{tickets.map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.subject}</option>)}</select></label><label className="block"><span className="text-sm font-medium text-ink-700">Work note <span className="text-semantic-danger">*</span></span><textarea className="input-base mt-2 min-h-24 w-full resize-y" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the work completed" /></label><div className="grid grid-cols-2 gap-3"><label><span className="text-sm font-medium text-ink-700">Hours</span><input className="input-base mt-2 w-full" type="number" min="0" value={hours} onChange={(event) => setHours(event.target.value)} /></label><label><span className="text-sm font-medium text-ink-700">Minutes</span><input className="input-base mt-2 w-full" type="number" min="0" max="59" value={minutes} onChange={(event) => setMinutes(event.target.value)} /></label></div><div className="rounded-xl bg-linen-200 px-4 py-3 text-sm text-ink-600" aria-live="polite">Total duration: <strong className="text-ink-700">{totalMinutes > 0 ? formatDuration(totalMinutes) : "Not set"}</strong></div></div>
  </Dialog>;
}
