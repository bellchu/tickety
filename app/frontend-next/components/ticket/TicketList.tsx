"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bookmark,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  Filter,
  Inbox,
  Plus,
  Search,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { Alert, Badge, Button, Dialog, EmptyState, ErrorState, IconButton, Skeleton } from "@/components/ui";
import { DataToolbar, PageFrame, PageHeader } from "@/components/layout/PageLayout";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { canAccessProtectedIntelligence } from "@/lib/auth";
import type { Ticket, TicketListSort } from "@/lib/types";
import { cn, formatTimeAgo } from "@/lib/utils";

const SAVED_VIEWS_KEY = "tickety.ticket-queue.views.v1";
const STATUS_FILTERS = ["Open", "Escalated", "Awaiting Review", "Closed"];
const PRIORITIES = ["P1", "P2", "P3", "P4"];
const PAGE_SIZES = [25, 50, 100];
const EMPTY_TICKETS: Ticket[] = [];
const SORT_OPTIONS: Array<{ value: TicketListSort; label: string }> = [
  { value: "newest", label: "Newest created" },
  { value: "updated", label: "Recently updated" },
  { value: "priority", label: "Highest priority" },
  { value: "complexity", label: "Most complex" },
  { value: "oldest", label: "Oldest created" },
];

interface SavedView {
  id: string;
  name: string;
  status: string;
  priority: string;
  assigneeId: string;
  category: string;
  sort: TicketListSort;
  limit: number;
  builtIn?: boolean;
}

const BUILT_IN_VIEWS: SavedView[] = [
  { id: "all", name: "All tickets", status: "", priority: "", assigneeId: "", category: "", sort: "newest", limit: 25, builtIn: true },
  { id: "open", name: "Open queue", status: "Open", priority: "", assigneeId: "", category: "", sort: "priority", limit: 25, builtIn: true },
  { id: "p1", name: "P1 incidents", status: "", priority: "P1", assigneeId: "", category: "", sort: "oldest", limit: 25, builtIn: true },
  { id: "escalated", name: "Escalations", status: "Escalated", priority: "", assigneeId: "", category: "", sort: "updated", limit: 25, builtIn: true },
];

function badgeForPriority(priority: string): "danger" | "warning" | "info" | "neutral" {
  if (priority === "P1") return "danger";
  if (priority === "P2") return "warning";
  if (priority === "P3") return "info";
  return "neutral";
}

function badgeForStatus(status: string): "success" | "warning" | "info" | "neutral" {
  const normalized = status.toLowerCase();
  if (["closed", "resolved", "completed"].includes(normalized)) return "success";
  if (["escalated", "awaiting review", "pending"].includes(normalized)) return "warning";
  if (["open", "new", "in progress"].includes(normalized)) return "info";
  return "neutral";
}

function csvCell(value: unknown) {
  let text = value == null ? "" : String(value);
  if (/^\s*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function exportPage(tickets: Ticket[]) {
  const columns: Array<[string, (ticket: Ticket) => unknown]> = [
    ["Ticket ID", (ticket) => ticket.id],
    ["Subject", (ticket) => ticket.subject],
    ["Description", (ticket) => ticket.description],
    ["Status", (ticket) => ticket.status],
    ["Priority", (ticket) => ticket.priority],
    ["Reporter", (ticket) => ticket.reporter],
    ["Assignee", (ticket) => ticket.assignee_name],
    ["Category", (ticket) => ticket.category],
    ["Created", (ticket) => ticket.created_at],
    ["Updated", (ticket) => ticket.updated_at],
  ];
  const rows = [
    columns.map(([label]) => csvCell(label)).join(","),
    ...tickets.map((ticket) => columns.map(([, getValue]) => csvCell(getValue(ticket))).join(",")),
  ];
  const blob = new Blob([`\uFEFF${rows.join("\r\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `tickety-queue-page-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function LoadingQueue() {
  return (
    <div aria-label="Loading tickets" aria-busy="true" className="rounded-2xl border border-linen-400 bg-linen-50 p-5">
      <span className="sr-only">Loading tickets</span>
      <div className="space-y-3">
        {[0, 1, 2, 3, 4, 5].map((row) => <Skeleton key={row} className="h-14 w-full" />)}
      </div>
    </div>
  );
}

export function TicketList({ onCreate }: { onCreate?: () => void }) {
  const queryClient = useQueryClient();
  const selectAllRef = useRef<HTMLInputElement>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState<TicketListSort>("newest");
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeViewId, setActiveViewId] = useState("all");
  const [customViews, setCustomViews] = useState<SavedView[]>([]);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [viewName, setViewName] = useState("");
  const [bulkAction, setBulkAction] = useState("");
  const [bulkValue, setBulkValue] = useState("");
  const [closeConfirmOpen, setCloseConfirmOpen] = useState(false);
  const [moreFiltersOpen, setMoreFiltersOpen] = useState(false);
  const [bulkNotice, setBulkNotice] = useState<{ variant: "success" | "danger"; message: string } | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(SAVED_VIEWS_KEY);
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        const validSorts = new Set(SORT_OPTIONS.map((option) => option.value));
        const normalized = parsed.flatMap((view, index): SavedView[] => {
          if (!view || typeof view.id !== "string" || typeof view.name !== "string") return [];
          const safeText = (value: unknown, maxLength: number) => typeof value === "string" ? value.slice(0, maxLength) : "";
          return [{
            id: safeText(view.id, 80) || `saved-import-${index}`,
            name: safeText(view.name, 60) || "Saved view",
            status: safeText(view.status, 100),
            priority: safeText(view.priority, 100),
            assigneeId: safeText(view.assigneeId, 255),
            category: safeText(view.category, 100),
            sort: validSorts.has(view.sort) ? view.sort : "newest",
            limit: PAGE_SIZES.includes(view.limit) ? view.limit : 25,
          }];
        });
        setCustomViews(normalized.slice(0, 20));
      }
    } catch {
      // A corrupt or unavailable local store should not block the queue.
    }
  }, []);

  const pageQuery = useQuery({
    queryKey: ["ticket-page", { status, priority, assigneeId, category, search, sort, limit, offset }],
    queryFn: () => api.getTicketsPage({ status, priority, assigneeId, category, search, sort, limit, offset }),
    placeholderData: (previous) => previous,
  });
  const meQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canBulk = canAccessProtectedIntelligence(meQuery.data);
  const categoriesQuery = useQuery({ queryKey: queryKeys.ticketCategories, queryFn: api.getCategories, retry: false });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: api.getUsers, enabled: canBulk, retry: false });

  const tickets = pageQuery.data?.tickets ?? EMPTY_TICKETS;
  const pageTransitioning = pageQuery.isPlaceholderData && pageQuery.isFetching;
  const pageIds = useMemo(() => tickets.map((ticket) => ticket.id), [tickets]);
  const selectedOnPage = pageIds.filter((id) => selected.has(id)).length;
  const allOnPageSelected = pageIds.length > 0 && selectedOnPage === pageIds.length;
  const someOnPageSelected = selectedOnPage > 0 && !allOnPageSelected;
  const activeFilterCount = [status, priority, assigneeId, category].filter(Boolean).length;

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someOnPageSelected;
  }, [someOnPageSelected]);

  useEffect(() => {
    setSelected(new Set());
    setBulkNotice(null);
  }, [status, priority, assigneeId, category, search, sort, limit, offset]);

  const bulkMutation = useMutation({
    mutationFn: ({ action, value }: { action: string; value?: string }) => api.bulkAction(Array.from(selected), action, value),
    onSuccess: (result) => {
      setBulkNotice({ variant: "success", message: `${result.updated} ${result.updated === 1 ? "ticket" : "tickets"} updated.` });
      setSelected(new Set());
      setBulkAction("");
      setBulkValue("");
      void queryClient.invalidateQueries({ queryKey: ["ticket-page"] });
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
    onError: (error) => setBulkNotice({ variant: "danger", message: error instanceof Error ? error.message : "The bulk update failed." }),
  });

  const markFiltersChanged = () => {
    setActiveViewId("");
    setOffset(0);
  };

  const applyView = (view: SavedView) => {
    setStatus(view.status);
    setPriority(view.priority);
    setAssigneeId(view.assigneeId);
    setCategory(view.category);
    setSort(view.sort);
    setLimit(view.limit);
    setOffset(0);
    setActiveViewId(view.id);
  };

  const saveView = () => {
    const name = viewName.trim();
    if (!name) return;
    const view: SavedView = {
      id: `saved-${Date.now()}`,
      name: name.slice(0, 60),
      status,
      priority,
      assigneeId,
      category,
      sort,
      limit,
    };
    const next = [...customViews, view].slice(-20);
    setCustomViews(next);
    setActiveViewId(view.id);
    setViewName("");
    setSaveDialogOpen(false);
    try { window.localStorage.setItem(SAVED_VIEWS_KEY, JSON.stringify(next)); } catch { /* non-blocking */ }
  };

  const deleteView = (id: string) => {
    const next = customViews.filter((view) => view.id !== id);
    setCustomViews(next);
    if (activeViewId === id) setActiveViewId("");
    try { window.localStorage.setItem(SAVED_VIEWS_KEY, JSON.stringify(next)); } catch { /* non-blocking */ }
  };

  const clearFilters = () => {
    setSearchInput("");
    setSearch("");
    applyView(BUILT_IN_VIEWS[0]);
  };

  const toggleTicket = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const togglePage = () => {
    setSelected((current) => {
      const next = new Set(current);
      if (allOnPageSelected) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const runBulkAction = () => {
    if (!bulkAction || selected.size === 0) return;
    if (bulkAction === "close") {
      setCloseConfirmOpen(true);
      return;
    }
    if (!bulkValue) return;
    bulkMutation.mutate({ action: bulkAction, value: bulkValue });
  };

  const start = pageQuery.data && tickets.length ? pageQuery.data.offset + 1 : 0;
  const end = pageQuery.data ? pageQuery.data.offset + tickets.length : 0;

  return (
    <PageFrame width="wide">
      <PageHeader
        eyebrow="Support operations"
        icon={<Inbox className="h-3.5 w-3.5" />}
        title="Tickets"
        description="Search, prioritize, and move requests through the support workflow."
        actions={
          <>
          <Button variant="secondary" onClick={() => exportPage(tickets)} disabled={!tickets.length || pageQuery.isLoading || pageTransitioning} leadingIcon={<Download className="h-4 w-4" />}>Export page</Button>
          {onCreate && <Button onClick={onCreate} leadingIcon={<Plus className="h-4 w-4" />}>New ticket</Button>}
          </>
        }
      />

      <DataToolbar label="Ticket queue controls" className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 border-b border-linen-300 pb-4">
          <span id="saved-views-title" className="mr-1 inline-flex items-center gap-1.5 text-xs font-semibold text-ink-500"><Bookmark className="h-3.5 w-3.5" aria-hidden="true" />Saved views</span>
          {[...BUILT_IN_VIEWS, ...customViews].map((view) => (
            <div key={view.id} className="inline-flex items-center">
              <button type="button" aria-pressed={activeViewId === view.id} onClick={() => applyView(view)} className={cn("min-h-8 rounded-lg border px-3 text-xs font-semibold transition-colors", activeViewId === view.id ? "border-clay-300 bg-[var(--color-primary-soft)] text-semantic-primary" : "border-linen-400 bg-linen-50 text-ink-500 hover:bg-linen-200", !view.builtIn && "rounded-r-none")}>{view.name}</button>
              {!view.builtIn && <IconButton icon={<Trash2 className="h-3.5 w-3.5" />} aria-label={`Delete saved view ${view.name}`} size="sm" variant="secondary" onClick={() => deleteView(view.id)} className="rounded-l-none border-l-0" />}
            </div>
          ))}
          <Button variant="ghost" size="sm" onClick={() => setSaveDialogOpen(true)} leadingIcon={<Plus className="h-3.5 w-3.5" />}>Save current</Button>
        </div>

        <div className="space-y-3">
        <div className="flex flex-col gap-3 lg:flex-row">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
            <input type="search" value={searchInput} onChange={(event) => { setSearchInput(event.target.value); setActiveViewId(""); }} className="input-base input-search pr-10" placeholder="Search subject, description, requester, or external ID" aria-label="Search tickets" />
            {searchInput && <button type="button" onClick={() => setSearchInput("")} aria-label="Clear search" className="absolute right-2 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-md text-ink-400 hover:bg-linen-300 hover:text-ink-600"><X className="h-3.5 w-3.5" aria-hidden="true" /></button>}
          </div>
          <label className="min-w-44"><span className="sr-only">Sort tickets</span><select value={sort} onChange={(event) => { setSort(event.target.value as TicketListSort); markFiltersChanged(); }} className="input-base"><option disabled>Sort tickets</option>{SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        </div>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-500"><Filter className="h-3.5 w-3.5" aria-hidden="true" />Status</span>
            <button type="button" aria-pressed={!status} onClick={() => { setStatus(""); markFiltersChanged(); }} className={cn("min-h-11 rounded-full border px-3 text-xs font-semibold sm:min-h-8", !status ? "border-clay-300 bg-[var(--color-primary-soft)] text-semantic-primary" : "border-linen-400 text-ink-500 hover:bg-linen-200")}>All</button>
            {STATUS_FILTERS.map((item) => <button key={item} type="button" aria-pressed={status === item} onClick={() => { setStatus(item); markFiltersChanged(); }} className={cn("min-h-11 rounded-full border px-3 text-xs font-semibold sm:min-h-8", status === item ? "border-clay-300 bg-[var(--color-primary-soft)] text-semantic-primary" : "border-linen-400 text-ink-500 hover:bg-linen-200")}>{item}</button>)}
          </div>
          <Button
            variant="secondary"
            size="sm"
            aria-expanded={moreFiltersOpen}
            aria-controls="ticket-more-filters"
            onClick={() => setMoreFiltersOpen((open) => !open)}
            leadingIcon={<Filter className="h-3.5 w-3.5" />}
          >
            More filters{activeFilterCount > (status ? 1 : 0) ? ` (${activeFilterCount - (status ? 1 : 0)})` : ""}
          </Button>
        </div>
        {moreFiltersOpen && <div id="ticket-more-filters" className="grid gap-3 border-t border-linen-300 pt-3 sm:grid-cols-2 lg:grid-cols-4">
          <label><span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-400">Priority</span><select value={priority} onChange={(event) => { setPriority(event.target.value); markFiltersChanged(); }} className="input-base"><option value="">Any priority</option>{PRIORITIES.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label><span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-400">Category</span><select value={category} disabled={categoriesQuery.isError} onChange={(event) => { setCategory(event.target.value); markFiltersChanged(); }} className="input-base"><option value="">{categoriesQuery.isError ? "Categories unavailable" : "Any category"}</option>{(categoriesQuery.data ?? []).map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select></label>
          <label><span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-400">Assignee</span><select value={assigneeId} disabled={!canBulk || usersQuery.isError} onChange={(event) => { setAssigneeId(event.target.value); markFiltersChanged(); }} className="input-base"><option value="">{!canBulk ? "Supervisor access required" : usersQuery.isError ? "Assignees unavailable" : "Any assignee"}</option>{(usersQuery.data ?? []).filter((user) => user.is_active).map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}</select></label>
          <label><span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-400">Rows per page</span><select value={limit} onChange={(event) => { setLimit(Number(event.target.value)); markFiltersChanged(); }} className="input-base">{PAGE_SIZES.map((size) => <option key={size} value={size}>{size} rows</option>)}</select></label>
        </div>}
        {(activeFilterCount > 0 || searchInput) && (
          <div className="flex flex-col gap-3 border-t border-linen-300 pt-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap gap-2" aria-label="Applied ticket filters">
              {searchInput && <FilterChip label={`Search: ${searchInput}`} onRemove={() => setSearchInput("")} />}
              {status && <FilterChip label={`Status: ${status}`} onRemove={() => { setStatus(""); markFiltersChanged(); }} />}
              {priority && <FilterChip label={`Priority: ${priority}`} onRemove={() => { setPriority(""); markFiltersChanged(); }} />}
              {category && <FilterChip label={`Category: ${category}`} onRemove={() => { setCategory(""); markFiltersChanged(); }} />}
              {assigneeId && <FilterChip label={`Assignee: ${(usersQuery.data ?? []).find((user) => user.id === assigneeId)?.name || "Selected"}`} onRemove={() => { setAssigneeId(""); markFiltersChanged(); }} />}
            </div>
            <Button variant="ghost" size="sm" onClick={clearFilters}>Clear all</Button>
          </div>
        )}
        </div>
      </DataToolbar>

      {(categoriesQuery.isError || (canBulk && usersQuery.isError)) && (
        <Alert
          variant="warning"
          title="Some filter options are unavailable"
          action={<Button variant="secondary" size="sm" onClick={() => { void categoriesQuery.refetch(); if (canBulk) void usersQuery.refetch(); }} pending={categoriesQuery.isFetching || usersQuery.isFetching} pendingLabel="Retrying…">Retry</Button>}
        >
          The ticket queue is current, but category or assignee choices could not be loaded. Unavailable controls are disabled.
        </Alert>
      )}

      {canBulk && selected.size > 0 && (
        <section aria-label="Bulk actions" className="sticky top-20 z-20 flex flex-col gap-3 rounded-2xl border border-clay-200 bg-[var(--color-primary-soft)] p-4 shadow-[var(--shadow-raised)] lg:flex-row lg:items-center">
          <div className="min-w-32"><p className="text-sm font-semibold text-ink-700">{selected.size} selected</p><button type="button" onClick={() => setSelected(new Set())} className="mt-0.5 text-xs font-medium text-semantic-primary hover:underline">Clear selection</button></div>
          <div className="grid flex-1 gap-2 sm:grid-cols-2">
            <label><span className="sr-only">Bulk action</span><select value={bulkAction} onChange={(event) => { setBulkAction(event.target.value); setBulkValue(""); }} className="input-base bg-white"><option value="">Choose bulk action</option><option value="close">Close tickets</option><option value="set_priority">Set priority</option><option value="set_category">Set category</option><option value="assign">Assign owner</option></select></label>
            {bulkAction === "set_priority" && <label><span className="sr-only">New priority</span><select value={bulkValue} onChange={(event) => setBulkValue(event.target.value)} className="input-base bg-white"><option value="">Choose priority</option>{PRIORITIES.map((item) => <option key={item}>{item}</option>)}</select></label>}
            {bulkAction === "set_category" && <label><span className="sr-only">New category</span><select value={bulkValue} onChange={(event) => setBulkValue(event.target.value)} className="input-base bg-white"><option value="">Choose category</option>{(categoriesQuery.data ?? []).map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select></label>}
            {bulkAction === "assign" && <label><span className="sr-only">New assignee</span><select value={bulkValue} onChange={(event) => setBulkValue(event.target.value)} className="input-base bg-white"><option value="">Choose assignee</option>{(usersQuery.data ?? []).filter((user) => user.is_active).map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}</select></label>}
          </div>
          <Button onClick={runBulkAction} disabled={!bulkAction || (bulkAction !== "close" && !bulkValue)} pending={bulkMutation.isPending} pendingLabel="Applying…">Apply</Button>
        </section>
      )}

      {bulkNotice && <Alert variant={bulkNotice.variant} title={bulkNotice.variant === "success" ? "Bulk update complete" : "Bulk update failed"}>{bulkNotice.message}</Alert>}

      {pageQuery.isLoading || pageTransitioning ? <LoadingQueue /> : pageQuery.isError ? (
        <ErrorState title="Tickets could not be loaded" description="The queue is unavailable, so no ticket data is being shown. Check the connection and retry." actionLabel="Retry queue" onRetry={() => void pageQuery.refetch()} retrying={pageQuery.isFetching} />
      ) : tickets.length === 0 ? (
        <EmptyState title={activeFilterCount || search ? "No tickets match this view" : "No tickets yet"} description={activeFilterCount || search ? "Try removing a filter or changing the search terms." : onCreate ? "Create a ticket to start the support queue." : "No tickets are available in this workspace."} icon={<Inbox className="h-5 w-5" />} action={activeFilterCount || search ? <Button variant="secondary" onClick={clearFilters}>Clear filters</Button> : onCreate ? <Button variant="secondary" onClick={onCreate}>Create ticket</Button> : undefined} />
      ) : (
        <>
          <div className="hidden overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm md:block">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left">
                <caption className="sr-only">Tickets in the current server-filtered page</caption>
                <thead className="border-b border-linen-300 bg-linen-100 text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-400">
                  <tr>
                    {canBulk && <th scope="col" className="w-12 px-4 py-3"><input ref={selectAllRef} type="checkbox" checked={allOnPageSelected} onChange={togglePage} aria-label="Select all tickets on this page" className="h-4 w-4" /></th>}
                    <th scope="col" className="px-4 py-3">Ticket</th><th scope="col" className="px-4 py-3">Requester</th><th scope="col" className="px-4 py-3">Priority</th><th scope="col" className="px-4 py-3">Status</th><th scope="col" className="px-4 py-3">Assignee</th><th scope="col" className="px-4 py-3 text-right">Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-linen-300">
                  {tickets.map((ticket) => (
                    <tr key={ticket.id} className={cn("transition-colors hover:bg-linen-100", selected.has(ticket.id) && "bg-[var(--color-primary-soft)]/60")}>
                      {canBulk && <td className="px-4 py-4"><input type="checkbox" checked={selected.has(ticket.id)} onChange={() => toggleTicket(ticket.id)} aria-label={`Select ${ticket.subject}`} className="h-4 w-4" /></td>}
                      <td className="max-w-[28rem] px-4 py-4"><Link href={`/tickets/${ticket.id}`} className="block truncate text-sm font-semibold text-ink-700 hover:text-semantic-primary hover:underline">{ticket.subject}</Link><div className="mt-1 flex items-center gap-2"><span className="font-mono text-[11px] text-ink-400">{ticket.id}</span>{ticket.category && <span className="truncate text-[11px] text-ink-400">· {ticket.category}</span>}</div></td>
                      <td className="max-w-44 px-4 py-4"><span className="block truncate text-xs text-ink-500">{ticket.reporter || "Unknown"}</span></td>
                      <td className="px-4 py-4"><Badge variant={badgeForPriority(ticket.priority)}>{ticket.priority}</Badge></td>
                      <td className="px-4 py-4"><Badge variant={badgeForStatus(ticket.status)} dot>{ticket.status}</Badge></td>
                      <td className="px-4 py-4"><span className="inline-flex max-w-40 items-center gap-1.5 truncate text-xs text-ink-500"><UserRound className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />{ticket.assignee_name || "Unassigned"}</span></td>
                      <td className="px-4 py-4 text-right"><span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-400"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />{formatTimeAgo(ticket.updated_at || ticket.created_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="grid gap-3 md:hidden">
            {tickets.map((ticket) => (
              <article key={ticket.id} className={cn("rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm", selected.has(ticket.id) && "border-clay-300 bg-[var(--color-primary-soft)]/50")}>
                <div className="flex items-start gap-3">
                  {canBulk && <input type="checkbox" checked={selected.has(ticket.id)} onChange={() => toggleTicket(ticket.id)} aria-label={`Select ${ticket.subject}`} className="mt-1 h-4 w-4 shrink-0" />}
                  <div className="min-w-0 flex-1"><div className="flex flex-wrap gap-1.5"><Badge variant={badgeForPriority(ticket.priority)}>{ticket.priority}</Badge><Badge variant={badgeForStatus(ticket.status)} dot>{ticket.status}</Badge></div><Link href={`/tickets/${ticket.id}`} className="mt-3 block text-sm font-semibold leading-5 text-ink-700 hover:text-semantic-primary">{ticket.subject}</Link><p className="mt-1 truncate font-mono text-[11px] text-ink-400">{ticket.id}</p></div>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-linen-300 pt-3 text-xs"><div><dt className="text-ink-400">Requester</dt><dd className="mt-1 truncate font-medium text-ink-600">{ticket.reporter || "Unknown"}</dd></div><div><dt className="text-ink-400">Assignee</dt><dd className="mt-1 truncate font-medium text-ink-600">{ticket.assignee_name || "Unassigned"}</dd></div></dl>
                <p className="mt-3 flex items-center gap-1.5 text-[11px] text-ink-400"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />Updated {formatTimeAgo(ticket.updated_at || ticket.created_at)}</p>
              </article>
            ))}
          </div>
        </>
      )}

      {!pageQuery.isError && !pageQuery.isLoading && !pageTransitioning && (
        <nav aria-label="Ticket queue pagination" className="flex flex-col gap-3 rounded-2xl border border-linen-400 bg-linen-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-ink-500">Showing <span className="font-semibold text-ink-700">{start}–{end}</span>{pageQuery.data?.hasMore ? " · More results available" : " · End of results"}</p>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={offset === 0 || pageQuery.isFetching} onClick={() => setOffset(Math.max(0, offset - limit))} leadingIcon={<ChevronLeft className="h-3.5 w-3.5" />}>Previous</Button>
            <span className="min-w-16 text-center text-xs font-semibold text-ink-500">Page {Math.floor(offset / limit) + 1}</span>
            <Button variant="secondary" size="sm" disabled={!pageQuery.data?.hasMore || pageQuery.isFetching} onClick={() => setOffset(offset + limit)} trailingIcon={<ChevronRight className="h-3.5 w-3.5" />}>Next</Button>
          </div>
        </nav>
      )}

      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen} title="Save current view" description="Save the structured filters, sort, and page size. Search terms are not stored on this device." footer={<><Button variant="secondary" onClick={() => setSaveDialogOpen(false)}>Cancel</Button><Button onClick={saveView} disabled={!viewName.trim()}>Save view</Button></>}>
        <label><span className="text-xs font-semibold text-ink-600">View name</span><input autoFocus value={viewName} maxLength={60} onChange={(event) => setViewName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); saveView(); } }} className="input-base mt-1.5" placeholder="e.g. Database escalations" /></label>
      </Dialog>

      <Dialog
        open={closeConfirmOpen}
        onOpenChange={(open) => { if (!bulkMutation.isPending) setCloseConfirmOpen(open); }}
        title={`Close ${selected.size} ${selected.size === 1 ? "ticket" : "tickets"}?`}
        description="This updates the selected tickets and their workflow status to Closed. The change is recorded in each ticket's audit log."
        role="alertdialog"
        dismissible={!bulkMutation.isPending}
        closeOnBackdrop={!bulkMutation.isPending}
        footer={<><Button variant="secondary" onClick={() => setCloseConfirmOpen(false)} disabled={bulkMutation.isPending}>Keep open</Button><Button variant="destructive" pending={bulkMutation.isPending} pendingLabel="Closing…" onClick={() => bulkMutation.mutate({ action: "close" }, { onSuccess: () => setCloseConfirmOpen(false) })}>Close tickets</Button></>}
      />
    </PageFrame>
  );
}

function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex min-h-7 items-center gap-1 rounded-full border border-linen-400 bg-linen-100 pl-2.5 pr-1 text-[11px] font-semibold text-ink-500">
      <span className="max-w-52 truncate">{label}</span>
      <button type="button" onClick={onRemove} aria-label={`Remove ${label}`} className="grid h-8 w-8 place-items-center rounded-full hover:bg-linen-300 hover:text-ink-700 sm:h-6 sm:w-6">
        <X className="h-3 w-3" aria-hidden="true" />
      </button>
    </span>
  );
}
