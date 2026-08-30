"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  Eye,
  Link,
  Pencil,
  Plus,
  Search,
  Trash2,
  Unlink,
} from "lucide-react";
import { api } from "@/lib/api";
import { canManageOperationalRecords } from "@/lib/auth";
import type { Problem, Ticket, UserOut } from "@/lib/types";
import { cn, formatTimeAgo, priorityColor, statusColor } from "@/lib/utils";
import {
  Alert,
  Button,
  ConfirmDialog,
  DataListCard,
  DataTable,
  DataTableViewport,
  Dialog,
  EmptyState,
  ErrorState,
  IconButton,
  ListText,
  Skeleton,
} from "@/components/ui";
import { PageFrame, PageHeader, SummaryStrip } from "@/components/layout/PageLayout";

const STATUS_FILTERS = ["", "New", "Under Investigation", "Known Error", "Resolved", "Closed"];
const PRIORITIES = ["P1", "P2", "P3", "P4"];
const PROBLEM_PAGE_SIZE = 25;
const PROBLEM_TICKET_PAGE_SIZE = 50;

type ProblemPayload = {
  title: string;
  description?: string;
  priority?: string;
  status?: string;
  category?: string | null;
  assigned_to?: string | null;
  impact_scope?: string | null;
  root_cause?: string | null;
  workaround?: string | null;
  resolution?: string | null;
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : error ? String(error) : "An unexpected error occurred.";
}

function StatusPill({ value }: { value: string }) {
  return <span className={cn("inline-flex max-w-full whitespace-normal rounded-xl border px-2.5 py-1 text-[11px] font-semibold leading-4 [overflow-wrap:anywhere]", statusColor(value))}>{value}</span>;
}

function PriorityPill({ value }: { value: string }) {
  return <span className={cn("inline-flex max-w-full whitespace-normal rounded-xl border px-2.5 py-1 text-[11px] font-semibold leading-4 [overflow-wrap:anywhere]", priorityColor(value))}>{value}</span>;
}

export default function ProblemsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [formProblem, setFormProblem] = useState<Problem | null | undefined>(undefined);
  const [viewing, setViewing] = useState<Problem | null>(null);
  const [deleting, setDeleting] = useState<Problem | null>(null);

  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManage = canManageOperationalRecords(authQuery.data);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  const problemsQuery = useInfiniteQuery({
    queryKey: ["problems", statusFilter, debouncedSearch],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getProblemsPage({
      status: statusFilter || undefined,
      search: debouncedSearch || undefined,
      limit: PROBLEM_PAGE_SIZE,
      offset: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.hasMore
      ? lastPage.offset + lastPage.limit
      : undefined,
  });
  const usersQuery = useQuery({ queryKey: ["users", "problem-options"], queryFn: () => api.getUsersPage({ isActive: true, limit: 200 }), enabled: canManage });

  const createMutation = useMutation({
    mutationFn: (payload: ProblemPayload) => api.createProblem(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["problems"] });
      setFormProblem(undefined);
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<Problem> }) => api.updateProblem(id, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["problems"] });
      setFormProblem(undefined);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteProblem(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["problems"] });
      setDeleting(null);
    },
    onError: () => setDeleting(null),
  });

  const problems = useMemo(
    () => problemsQuery.data?.pages.flatMap((page) => page.problems) ?? [],
    [problemsQuery.data],
  );
  const filtered = problems;
  const firstPage = problemsQuery.data?.pages[0];
  const summary = firstPage?.summary;
  const totalProblems = summary?.total ?? 0;
  const investigating = summary?.investigating ?? 0;
  const knownErrors = summary?.knownErrors ?? 0;
  const linked = summary?.linkedTickets ?? 0;
  const filteredTotal = firstPage?.total;
  const hasFilters = Boolean(statusFilter || debouncedSearch);

  const resetMutationErrors = () => {
    createMutation.reset();
    updateMutation.reset();
  };

  return (
    <PageFrame width="wide" className="pb-10">
      <PageHeader eyebrow="Service governance" icon={<AlertOctagon className="h-4 w-4" />} title="Problems" description="Investigate recurring incidents, document root causes, and connect durable fixes to affected tickets." actions={canManage ? <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { resetMutationErrors(); setFormProblem(null); }}>New problem</Button> : undefined} />

      {authQuery.isError && <Alert variant="warning" title="Management access could not be verified">Problem records remain visible, but write controls are hidden until the session check succeeds.</Alert>}
      {usersQuery.data?.hasMore && <Alert variant="info" title="Assignee directory is truncated">The first 200 active accounts are available for problem ownership. Search the Agents directory before assigning an account outside this list.</Alert>}

      {(totalProblems > 0 || investigating > 0 || knownErrors > 0 || linked > 0) && <SummaryStrip label="Problem overview" className="xl:grid-cols-4">
        {[
          { label: "Total problems", value: totalProblems, note: "All governed problem records" },
          { label: "Investigating", value: investigating, note: "Root cause work in progress" },
          { label: "Known errors", value: knownErrors, note: "Workarounds should be documented" },
          { label: "Linked tickets", value: linked, note: "Incident context connected" },
        ].map((metric) => (
          <div key={metric.label} className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-[var(--shadow-card)]">
            <p className="text-xs font-medium text-ink-500">{metric.label}</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-ink-800">{metric.value}</p>
            <p className="mt-1 text-xs text-ink-400">{metric.note}</p>
          </div>
        ))}
      </SummaryStrip>}

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-[var(--shadow-card)]">
        <div className="flex flex-col gap-3 border-b border-linen-400 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink-800">Problem register</h2>
            <p className="mt-0.5 text-xs text-ink-500" aria-live="polite">{problemsQuery.isLoading ? "Loading problem records…" : `${filtered.length}${filteredTotal === undefined ? "" : ` of ${filteredTotal}`} ${(filteredTotal ?? filtered.length) === 1 ? "record" : "records"} loaded${problemsQuery.hasNextPage ? "; more available" : ""}`}</p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <label className="relative">
              <span className="sr-only">Search problems</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
              <input className="input-base min-h-10 pl-9 sm:w-64" type="search" maxLength={200} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search title, category, owner…" />
            </label>
            <label>
              <span className="sr-only">Filter by status</span>
              <select className="input-base min-h-10 sm:w-52" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                {STATUS_FILTERS.map((status) => <option key={status || "all"} value={status}>{status || "All statuses"}</option>)}
              </select>
            </label>
          </div>
        </div>

        {deleteMutation.error && <div className="p-4 pb-0"><Alert variant="danger" title="Problem was not deleted">{errorMessage(deleteMutation.error)}</Alert></div>}
        {problemsQuery.isLoading ? <RegisterSkeleton /> : problemsQuery.isError && !filtered.length ? (
          <div className="p-4"><ErrorState title="Problems could not be loaded" description={errorMessage(problemsQuery.error)} onRetry={() => problemsQuery.refetch()} retrying={problemsQuery.isFetching} /></div>
        ) : filtered.length === 0 ? (
          <div className="p-4"><EmptyState icon={<AlertOctagon className="h-5 w-5" />} title={hasFilters ? "No matching problems" : "No problems recorded"} description={hasFilters ? "Adjust the search or status filter to broaden this view." : canManage ? "Create a problem record when an issue needs structured root-cause analysis." : "No problem records are available."} action={hasFilters ? <Button variant="secondary" onClick={() => { setSearch(""); setDebouncedSearch(""); setStatusFilter(""); }}>Clear filters</Button> : canManage ? <Button onClick={() => setFormProblem(null)} leadingIcon={<Plus className="h-4 w-4" />}>Create first problem</Button> : undefined} /></div>
        ) : (
          <>
            <DataTableViewport label="Problem register" className="hidden md:block">
              <DataTable className="min-w-[700px]">
                <colgroup><col className="w-[34%]" /><col className="w-[20%]" /><col className="w-[20%]" /><col className="w-[16%]" /><col className="w-[10%]" /></colgroup>
                <thead className="border-b border-linen-400 bg-linen-100 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-500">
                  <tr><th className="px-5 py-3">Problem</th><th className="px-4 py-3">State</th><th className="px-4 py-3">Scope</th><th className="px-4 py-3">Owner</th><th className="px-5 py-3 text-right"><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody className="divide-y divide-linen-300">
                  {filtered.map((problem) => <ProblemRow key={problem.id} problem={problem} canManage={canManage} onView={() => setViewing(problem)} onEdit={() => { resetMutationErrors(); setFormProblem(problem); }} onDelete={() => { deleteMutation.reset(); setDeleting(problem); }} />)}
                </tbody>
              </DataTable>
            </DataTableViewport>
            <div className="grid gap-3 bg-linen-100/60 p-3 md:hidden">
              {filtered.map((problem) => <ProblemCard key={problem.id} problem={problem} canManage={canManage} onView={() => setViewing(problem)} onEdit={() => { resetMutationErrors(); setFormProblem(problem); }} onDelete={() => { deleteMutation.reset(); setDeleting(problem); }} />)}
            </div>
            {problemsQuery.isFetchNextPageError && <div className="border-t border-linen-300 p-4"><Alert variant="danger" title="More problems could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void problemsQuery.fetchNextPage()}>Retry</Button>}>The problem records already shown remain available.</Alert></div>}
            {problemsQuery.hasNextPage && !problemsQuery.isFetchNextPageError && <div className="flex justify-center border-t border-linen-300 p-4"><Button variant="secondary" onClick={() => void problemsQuery.fetchNextPage()} pending={problemsQuery.isFetchingNextPage} pendingLabel="Loading more…">Load more problems</Button></div>}
          </>
        )}
      </section>

      {canManage && <ProblemFormDialog open={formProblem !== undefined} problem={formProblem ?? null} users={usersQuery.data?.users ?? []} usersUnavailable={usersQuery.isError} onOpenChange={(open) => { if (!open && !createMutation.isPending && !updateMutation.isPending) setFormProblem(undefined); }} onSubmit={(payload) => formProblem ? updateMutation.mutate({ id: formProblem.id, payload }) : createMutation.mutate(payload)} pending={createMutation.isPending || updateMutation.isPending} error={createMutation.error || updateMutation.error} />}
      <ProblemDetailDialog problem={viewing} canManage={canManage} onOpenChange={(open) => { if (!open) setViewing(null); }} />
      {canManage && <ConfirmDialog open={Boolean(deleting)} onOpenChange={(open) => { if (!open) setDeleting(null); }} title="Delete problem record?" description={<>This permanently removes <strong>{deleting?.title}</strong>. Linked incident records are not deleted.</>} confirmLabel="Delete problem" destructive pending={deleteMutation.isPending} onConfirm={() => { if (deleting) deleteMutation.mutate(deleting.id); }} />}
    </PageFrame>
  );
}

function RegisterSkeleton() {
  return <div className="space-y-3 p-5" role="status" aria-label="Loading problems"><Skeleton className="h-10 w-full" />{[1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-14 w-full" />)}</div>;
}

type ItemActions = { problem: Problem; canManage: boolean; onView: () => void; onEdit: () => void; onDelete: () => void };

function ProblemRow({ problem, canManage, onView, onEdit, onDelete }: ItemActions) {
  return <tr className="transition-colors hover:bg-linen-100/80">
    <td className="px-5 py-4"><button onClick={onView} className="block w-full min-w-0 text-left focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"><ListText text={problem.title} lines={2} className="font-semibold leading-5 text-ink-800" /><span className="mt-1 block font-mono text-[11px] text-ink-400">{problem.id.slice(0, 8).toUpperCase()}</span></button></td>
    <td className="px-4 py-4"><StatusPill value={problem.status} />{problem.priority && <div className="mt-2"><PriorityPill value={problem.priority} /></div>}</td>
    <td className="px-4 py-4"><ListText text={problem.category || "Uncategorized"} lines={2} className="text-xs font-medium text-ink-600" /><span className="mt-1 block text-[11px] tabular-nums text-ink-400">{problem.linked_tickets_count} linked ticket{problem.linked_tickets_count === 1 ? "" : "s"}</span></td><td className="px-4 py-4"><ListText text={problem.assigned_name || "Unassigned"} lines={2} className="text-xs text-ink-600" /></td>
    <td className="px-5 py-4"><div className="flex justify-end gap-1"><IconButton size="sm" aria-label={`View ${problem.title}`} icon={<Eye className="h-4 w-4" />} onClick={onView} />{canManage && <><IconButton size="sm" aria-label={`Edit ${problem.title}`} icon={<Pencil className="h-4 w-4" />} onClick={onEdit} /><IconButton size="sm" aria-label={`Delete ${problem.title}`} icon={<Trash2 className="h-4 w-4" />} onClick={onDelete} className="text-rust-600 hover:bg-rust-400/10" /></>}</div></td>
  </tr>;
}

function ProblemCard({ problem, canManage, onView, onEdit, onDelete }: ItemActions) {
  return <DataListCard><div className="flex min-w-0 items-start justify-between gap-3"><button onClick={onView} className="min-w-0 flex-1 text-left"><ListText text={problem.title} lines={2} className="font-semibold leading-5 text-ink-800" /><span className="mt-1 block font-mono text-[11px] text-ink-400">{problem.id.slice(0, 8).toUpperCase()}</span></button>{problem.priority && <PriorityPill value={problem.priority} />}</div><div className="mt-4 flex flex-wrap items-center gap-2"><StatusPill value={problem.status} /><ListText text={problem.category || "Uncategorized"} lines={2} className="w-full text-xs text-ink-500 xs:w-auto xs:max-w-[14rem]" /><span className="text-xs whitespace-nowrap text-ink-500">{problem.linked_tickets_count} linked</span></div><div className="mt-4 flex min-w-0 items-center justify-between gap-3 border-t border-linen-300 pt-3"><ListText text={problem.assigned_name || "Unassigned"} lines={2} className="flex-1 text-xs text-ink-500" /><div className="flex shrink-0 gap-1"><IconButton size="sm" aria-label={`View ${problem.title}`} icon={<Eye className="h-4 w-4" />} onClick={onView} />{canManage && <><IconButton size="sm" aria-label={`Edit ${problem.title}`} icon={<Pencil className="h-4 w-4" />} onClick={onEdit} /><IconButton size="sm" aria-label={`Delete ${problem.title}`} icon={<Trash2 className="h-4 w-4" />} onClick={onDelete} className="text-rust-600" /></>}</div></div></DataListCard>;
}

type ProblemFormProps = { open: boolean; problem: Problem | null; users: UserOut[]; usersUnavailable: boolean; onOpenChange: (open: boolean) => void; onSubmit: (payload: ProblemPayload) => void; pending: boolean; error: unknown };

function ProblemFormDialog(props: ProblemFormProps) {
  const key = props.problem?.id ?? (props.open ? "new" : "closed");
  return <ProblemFormDialogBody key={key} {...props} />;
}

function ProblemFormDialogBody({ open, problem, users, usersUnavailable, onOpenChange, onSubmit, pending, error }: ProblemFormProps) {
  const [title, setTitle] = useState(problem?.title ?? "");
  const [description, setDescription] = useState(problem?.description ?? "");
  const [priority, setPriority] = useState(problem?.priority ?? "P2");
  const [status, setStatus] = useState(problem?.status === "Investigating" ? "Under Investigation" : problem?.status ?? "New");
  const [category, setCategory] = useState(problem?.category ?? "");
  const [assignedTo, setAssignedTo] = useState(problem?.assigned_to ?? "");
  const [impactScope, setImpactScope] = useState(problem?.impact_scope ?? "");
  const [rootCause, setRootCause] = useState(problem?.root_cause ?? "");
  const [workaround, setWorkaround] = useState(problem?.workaround ?? "");
  const [resolution, setResolution] = useState(problem?.resolution ?? "");
  const [showInvestigation, setShowInvestigation] = useState(Boolean(problem?.root_cause || problem?.workaround || problem?.resolution));
  const optionalValue = (value: string) => value.trim() || (problem ? null : undefined);
  const closing = status === "Resolved" || status === "Closed";
  const closureReady = !closing || (Boolean(rootCause.trim()) && Boolean(workaround.trim() || resolution.trim()));

  return <Dialog open={open} onOpenChange={onOpenChange} title={problem ? "Edit problem" : "Create problem"} description="Capture the operational impact and ownership needed for root-cause work." dismissible={!pending} className="max-w-2xl" footer={<><Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button><Button pending={pending} pendingLabel={problem ? "Saving…" : "Creating…"} disabled={!title.trim() || !closureReady} onClick={() => onSubmit({ title: title.trim(), description: description.trim(), priority, category: optionalValue(category), assigned_to: optionalValue(assignedTo), impact_scope: optionalValue(impactScope), ...(problem ? { status, root_cause: optionalValue(rootCause), workaround: optionalValue(workaround), resolution: optionalValue(resolution) } : {}) })}>{problem ? "Save changes" : "Create problem"}</Button></>}>
    <div className="space-y-4">
      {Boolean(error) && <Alert variant="danger" title={problem ? "Changes were not saved" : "Problem was not created"}>{errorMessage(error)}</Alert>}
      {usersUnavailable && <Alert variant="warning" title="Assignees unavailable">The user directory could not be loaded. You can save this record without an assignee.</Alert>}
      <Field label="Title" required><input autoFocus className="input-base" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Concise description of the recurring issue" /></Field>
      <Field label="Description"><textarea className="input-base min-h-24 resize-y" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Observed behavior, frequency, and relevant context" /></Field>
      <div className="grid gap-4 sm:grid-cols-2"><Field label="Priority"><select className="input-base" value={priority} onChange={(event) => setPriority(event.target.value)}>{PRIORITIES.map((item) => <option key={item}>{item}</option>)}</select></Field><Field label="Category"><input className="input-base" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Network, identity, endpoint…" /></Field></div>
      <Field label="Assignee"><select className="input-base" value={assignedTo} onChange={(event) => setAssignedTo(event.target.value)} disabled={usersUnavailable}><option value="">Unassigned</option>{users.map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}</select></Field>
      <Field label="Impact scope"><textarea className="input-base min-h-20 resize-y" value={impactScope} onChange={(event) => setImpactScope(event.target.value)} placeholder="Affected services, teams, locations, or customers" /></Field>
      {problem && <section className="space-y-4 rounded-xl border border-linen-300 bg-linen-100 p-4"><div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><Field label="Lifecycle status"><select className="input-base sm:w-64" value={status} onChange={(event) => { setStatus(event.target.value); if (["Resolved", "Closed"].includes(event.target.value)) setShowInvestigation(true); }}>{STATUS_FILTERS.filter(Boolean).map((item) => <option key={item}>{item}</option>)}</select></Field><Button size="sm" variant="secondary" onClick={() => setShowInvestigation((value) => !value)}>{showInvestigation ? "Hide investigation notes" : "Add investigation notes"}</Button></div>{showInvestigation && <div className="space-y-4 border-t border-linen-300 pt-4"><Field label="Root cause"><textarea className="input-base min-h-20 resize-y" value={rootCause} onChange={(event) => setRootCause(event.target.value)} placeholder="Verified underlying cause" /></Field><Field label="Workaround"><textarea className="input-base min-h-20 resize-y" value={workaround} onChange={(event) => setWorkaround(event.target.value)} placeholder="Temporary mitigation for affected users" /></Field><Field label="Resolution"><textarea className="input-base min-h-20 resize-y" value={resolution} onChange={(event) => setResolution(event.target.value)} placeholder="Permanent corrective action" /></Field></div>}{closing && !closureReady && <Alert variant="warning" title="Closure evidence is incomplete">Add a root cause and either a workaround or resolution before closing this problem.</Alert>}</section>}
    </div>
  </Dialog>;
}

function ProblemDetailDialog({ problem, canManage, onOpenChange }: { problem: Problem | null; canManage: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [ticketId, setTicketId] = useState("");
  const [unlinking, setUnlinking] = useState<Ticket | null>(null);
  const detailQuery = useQuery({ queryKey: ["problem", problem?.id], queryFn: () => api.getProblem(problem!.id), enabled: Boolean(problem), initialData: problem ?? undefined });
  const ticketsQuery = useInfiniteQuery({
    queryKey: ["problem-tickets", problem?.id],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getProblemTicketsPage(problem!.id, {
      limit: PROBLEM_TICKET_PAGE_SIZE,
      offset: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.hasMore
      ? lastPage.offset + lastPage.limit
      : undefined,
    enabled: Boolean(problem),
  });
  const refreshLinks = async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["problem-tickets", problem?.id] }), queryClient.invalidateQueries({ queryKey: ["problems"] })]); };
  const linkMutation = useMutation({ mutationFn: (id: string) => api.linkTicketToProblem(problem!.id, id), onSuccess: async () => { await refreshLinks(); setTicketId(""); } });
  const unlinkMutation = useMutation({ mutationFn: (id: string) => api.unlinkTicketFromProblem(problem!.id, id), onSuccess: async () => { await refreshLinks(); setUnlinking(null); }, onError: () => setUnlinking(null) });
  const current = detailQuery.data ?? problem;
  const tickets = useMemo(
    () => ticketsQuery.data?.pages.flatMap((page) => page.tickets) ?? [],
    [ticketsQuery.data],
  );

  return <><Dialog open={Boolean(problem) && !unlinking} onOpenChange={onOpenChange} title={current?.title ?? "Problem details"} description={current ? `Problem ${current.id.slice(0, 8).toUpperCase()}` : undefined} className="max-w-3xl">
    {!current ? null : <div className="space-y-6">
      {detailQuery.isError && <Alert variant="warning" title="Latest record unavailable">Showing the last loaded data. {errorMessage(detailQuery.error)}</Alert>}
      <div className="flex flex-wrap gap-2"><StatusPill value={current.status} />{current.priority && <PriorityPill value={current.priority} />}<span className="rounded-full bg-linen-300 px-2.5 py-1 text-[11px] font-semibold text-ink-600">{current.category || "Uncategorized"}</span></div>
      <dl className="grid gap-4 rounded-xl border border-linen-400 bg-linen-100 p-4 sm:grid-cols-2"><Detail label="Owner" value={current.assigned_name || "Unassigned"} /><Detail label="Impact scope" value={current.impact_scope || "Not documented"} /><Detail label="Created" value={current.created_at ? formatTimeAgo(current.created_at) : "Unknown"} /><Detail label="Updated" value={current.updated_at ? formatTimeAgo(current.updated_at) : "Unknown"} /></dl>
      <Narrative label="Description" value={current.description} /><Narrative label="Root cause" value={current.root_cause} /><Narrative label="Workaround" value={current.workaround} /><Narrative label="Resolution" value={current.resolution} />
      <section className="border-t border-linen-400 pt-5"><div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><h3 className="text-sm font-semibold text-ink-800">Linked tickets</h3><p className="mt-1 text-xs text-ink-500">Incident evidence connected to this root-cause record.</p></div>{canManage && <div className="flex gap-2"><label className="min-w-0 flex-1 sm:w-56"><span className="sr-only">Ticket ID to link</span><input className="input-base min-h-10" value={ticketId} onChange={(event) => setTicketId(event.target.value)} placeholder="Ticket ID" /></label><Button size="sm" leadingIcon={<Link className="h-4 w-4" />} pending={linkMutation.isPending} pendingLabel="Linking…" disabled={!ticketId.trim()} onClick={() => linkMutation.mutate(ticketId.trim())}>Link</Button></div>}</div>
        {linkMutation.error && <Alert className="mt-4" variant="danger" title="Ticket was not linked">{errorMessage(linkMutation.error)}</Alert>}
        {unlinkMutation.error && <Alert className="mt-4" variant="danger" title="Ticket was not unlinked">{errorMessage(unlinkMutation.error)}</Alert>}
        <div className="mt-4">{ticketsQuery.isLoading ? <div className="space-y-2"><Skeleton className="h-12" /><Skeleton className="h-12" /></div> : ticketsQuery.isError && !tickets.length ? <ErrorState className="min-h-40" title="Linked tickets could not be loaded" description={errorMessage(ticketsQuery.error)} onRetry={() => ticketsQuery.refetch()} retrying={ticketsQuery.isFetching} /> : tickets.length ? <div className="space-y-3"><div className="divide-y divide-linen-300 rounded-xl border border-linen-400">{tickets.map((ticket) => <div key={ticket.id} className="flex min-w-0 items-center justify-between gap-3 p-3"><div className="min-w-0 flex-1"><ListText text={ticket.subject} lines={2} className="text-sm font-medium text-ink-700" /><ListText text={ticket.id} lines="wrap" className="mt-0.5 font-mono text-[11px] text-ink-400" /></div>{canManage && <IconButton size="sm" aria-label={`Unlink ${ticket.subject}`} icon={<Unlink className="h-4 w-4" />} onClick={() => { unlinkMutation.reset(); setUnlinking(ticket); }} />}</div>)}</div>{ticketsQuery.isFetchNextPageError && <Alert variant="danger" title="More linked tickets could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void ticketsQuery.fetchNextPage()}>Retry</Button>}>The linked tickets already shown remain available.</Alert>}{ticketsQuery.hasNextPage && !ticketsQuery.isFetchNextPageError && <div className="text-center"><Button size="sm" variant="secondary" onClick={() => void ticketsQuery.fetchNextPage()} pending={ticketsQuery.isFetchingNextPage} pendingLabel="Loading more…">Load more linked tickets</Button></div>}</div> : <EmptyState className="min-h-40" title="No linked tickets" description={canManage ? "Link the first incident using its ticket ID." : "No incident evidence is connected to this record."} />}</div>
      </section>
    </div>}
  </Dialog>{canManage && <ConfirmDialog open={Boolean(unlinking)} onOpenChange={(open) => { if (!open) setUnlinking(null); }} title="Unlink this ticket?" description={<>The ticket <strong>{unlinking?.subject}</strong> will no longer appear as evidence for this problem. The ticket itself is not deleted.</>} confirmLabel="Unlink ticket" destructive pending={unlinkMutation.isPending} onConfirm={() => { if (unlinking) unlinkMutation.mutate(unlinking.id); }} />}</>;
}

function Field({ label, required = false, children }: { label: string; required?: boolean; children: ReactNode }) { return <label className="block space-y-1.5"><span className="text-xs font-semibold text-ink-600">{label}{required && <span className="text-rust-600"> *</span>}</span>{children}</label>; }
function Detail({ label, value }: { label: string; value: string }) { return <div><dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">{label}</dt><dd className="mt-1 text-sm text-ink-700">{value}</dd></div>; }
function Narrative({ label, value }: { label: string; value: string | null }) { if (!value) return null; return <section><h3 className="text-xs font-semibold uppercase tracking-wider text-ink-400">{label}</h3><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-700">{value}</p></section>; }
