"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlarmClock,
  Archive,
  ArrowRight,
  ArrowUpRight,
  BellRing,
  Check,
  ChevronRight,
  Circle,
  Clock3,
  Copy,
  Inbox,
  ListFilter,
  MessageCircleReply,
  Search,
  Sparkles,
  Star,
  TimerReset,
  Users,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentWorkspaceFolder,
  AgentWorkspaceScope,
  AgentWorkspaceTicket,
} from "@/lib/types";
import {
  cn,
  formatTimeAgo,
  safeExternalUrl,
  statusColor,
} from "@/lib/utils";
import {
  formatOperationalTimestamp,
  requesterName,
  ticketLastCommunicationAt,
} from "@/lib/ticket-display";
import { FreshserviceConversationThread } from "@/components/ticket/FreshserviceConversationThread";
import { TicketPriorityIndicator } from "@/components/ticket/TicketPriorityIndicator";
import { TicketSentimentSubtitle } from "@/components/ticket/TicketSentimentSubtitle";
import { Alert, Badge, Button, EmptyState, ErrorState, IconButton, Skeleton } from "@/components/ui";
import { PageFrame } from "@/components/layout/PageLayout";

const MY_FOLDERS: Array<{
  id: AgentWorkspaceFolder;
  label: string;
  countKey?: string;
  icon: typeof Inbox;
}> = [
  { id: "inbox", label: "My Inbox", countKey: "inbox", icon: Inbox },
  { id: "needs_reply", label: "Needs reply", countKey: "needs_reply", icon: MessageCircleReply },
  { id: "sla_at_risk", label: "SLA at risk", countKey: "sla_at_risk", icon: TimerReset },
  { id: "starred", label: "Starred", countKey: "starred", icon: Star },
  { id: "follow_up", label: "Follow up", icon: AlarmClock },
  { id: "closed", label: "Closed", icon: Archive },
];

const VALID_FOLDERS = new Set<AgentWorkspaceFolder>([
  ...MY_FOLDERS.map((folder) => folder.id),
  "unassigned",
]);

const TEAM_FOLDERS: Array<{ id: AgentWorkspaceFolder; label: string }> = [
  { id: "inbox", label: "Inbox" },
  { id: "needs_reply", label: "Needs reply" },
  { id: "sla_at_risk", label: "SLA risk" },
  { id: "unassigned", label: "Unassigned" },
];

const AGENT_TICKET_PAGE_SIZE = 25;

function activeDeadline(ticket: AgentWorkspaceTicket) {
  if (ticket.needs_reply) {
    return ticket.response_due_at || ticket.external_fr_due_by || ticket.resolution_due_at || ticket.external_due_by;
  }
  return ticket.resolution_due_at || ticket.due_by || ticket.external_due_by;
}

function tomorrowAtNine() {
  const value = new Date();
  value.setDate(value.getDate() + 1);
  value.setHours(9, 0, 0, 0);
  return value.toISOString();
}

function folderLabel(folder: AgentWorkspaceFolder, scope: AgentWorkspaceScope) {
  if (scope === "team" && folder === "inbox") return "Team Inbox";
  if (folder === "unassigned") return "Unassigned";
  return MY_FOLDERS.find((item) => item.id === folder)?.label || "Inbox";
}

export function AgentWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState<"reply" | "link" | null>(null);
  const markedSeen = useRef(new Set<string>());
  const markingSeen = useRef(new Set<string>());

  const scope: AgentWorkspaceScope = searchParams.get("scope") === "team" ? "team" : "mine";
  const rawFolder = searchParams.get("folder") as AgentWorkspaceFolder | null;
  const folder = rawFolder && VALID_FOLDERS.has(rawFolder) ? rawFolder : "inbox";
  const teamId = scope === "team" ? searchParams.get("team") || undefined : undefined;
  const selectedId = searchParams.get("ticket") || undefined;

  const replaceParams = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    router.replace(`${pathname}${next.size ? `?${next.toString()}` : ""}`, { scroll: false });
  };

  const bootstrapQuery = useQuery({
    queryKey: ["agent-workspace", "bootstrap"],
    queryFn: api.getAgentWorkspaceBootstrap,
  });

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const ticketsKey = ["agent-workspace", "tickets", scope, teamId || "", folder, search] as const;
  const ticketsQuery = useInfiniteQuery({
    queryKey: ticketsKey,
    queryFn: ({ pageParam }) => api.getAgentWorkspaceTickets({
      scope,
      teamId,
      folder,
      search,
      limit: AGENT_TICKET_PAGE_SIZE,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, _pages, lastPageParam) => (
      lastPage.hasMore && lastPage.tickets.length > 0
        ? lastPageParam + lastPage.tickets.length
        : undefined
    ),
  });
  const tickets = useMemo(() => {
    const unique = new Map<string, AgentWorkspaceTicket>();
    for (const page of ticketsQuery.data?.pages ?? []) {
      for (const ticket of page.tickets) unique.set(ticket.id, ticket);
    }
    return Array.from(unique.values());
  }, [ticketsQuery.data?.pages]);
  const loadedSelected = tickets.find((ticket) => ticket.id === selectedId);
  const deepLinkedTicketQuery = useQuery({
    queryKey: [
      "agent-workspace",
      "selected-ticket",
      scope,
      teamId || "",
      folder,
      selectedId || "",
    ],
    queryFn: async () => {
      const page = await api.getAgentWorkspaceTickets({
        scope,
        teamId,
        folder,
        ticketId: selectedId,
        limit: 1,
      });
      return page.tickets.find((ticket) => ticket.id === selectedId) ?? null;
    },
    enabled: Boolean(
      selectedId
      && !loadedSelected
      && !ticketsQuery.isLoading
      && !ticketsQuery.isError
    ),
  });
  const selected = loadedSelected
    || deepLinkedTicketQuery.data
    || (!selectedId ? tickets[0] : undefined);

  useEffect(() => {
    if (tickets.length && !selectedId) {
      replaceParams({ ticket: tickets[0].id });
    }
    if (
      selectedId
      && !loadedSelected
      && deepLinkedTicketQuery.isSuccess
      && !deepLinkedTicketQuery.data
    ) {
      replaceParams({ ticket: tickets[0]?.id ?? null });
    }
    // replaceParams intentionally derives the latest URL state on render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, loadedSelected, tickets, deepLinkedTicketQuery.data, deepLinkedTicketQuery.isSuccess]);

  const stateMutation = useMutation({
    mutationFn: ({
      ticketId,
      update,
    }: {
      ticketId: string;
      update: Parameters<typeof api.updateAgentTicketState>[1];
    }) => api.updateAgentTicketState(ticketId, update),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-workspace"] });
    },
  });

  useEffect(() => {
    if (!selected?.is_unread || markedSeen.current.has(selected.id) || markingSeen.current.has(selected.id)) return;
    const ticketId = selected.id;
    markingSeen.current.add(ticketId);
    void api.updateAgentTicketState(ticketId, { mark_seen: true })
      .then(() => {
        markedSeen.current.add(ticketId);
        void queryClient.invalidateQueries({ queryKey: ["agent-workspace"] });
      })
      .catch(() => undefined)
      .finally(() => markingSeen.current.delete(ticketId));
    // The query client is stable for the mounted workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, selected?.is_unread]);

  const selectMyFolder = (nextFolder: AgentWorkspaceFolder) => {
    replaceParams({ scope: "mine", team: null, folder: nextFolder, ticket: null });
  };
  const selectTeam = (nextTeamId: string, nextFolder: AgentWorkspaceFolder = "inbox") => {
    replaceParams({ scope: "team", team: nextTeamId, folder: nextFolder, ticket: null });
  };
  const selectTeamFolder = (nextFolder: AgentWorkspaceFolder) => {
    if (teamId) replaceParams({ folder: nextFolder, ticket: null });
  };
  const selectedIndex = tickets.findIndex((ticket) => ticket.id === selected?.id);
  const nextTicket = selectedIndex >= 0 ? tickets[selectedIndex + 1] : undefined;

  const copyText = async (value: string, kind: "reply" | "link") => {
    await navigator.clipboard.writeText(value);
    setCopied(kind);
    window.setTimeout(() => setCopied(null), 1800);
  };

  return (
    <PageFrame width="wide" className="space-y-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.13em] text-semantic-primary">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" /> Focus workspace
          </div>
          <h1 className="mt-1 text-3xl font-medium tracking-[-0.035em] text-ink-700 sm:text-4xl">Agent</h1>
          <p className="mt-1 text-sm text-ink-500">Personal assignments, team queues, and the next best ticket in one place.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={!nextTicket}
            trailingIcon={<ArrowRight className="h-3.5 w-3.5" />}
            onClick={() => nextTicket && replaceParams({ ticket: nextTicket.id })}
          >
            Next ticket
          </Button>
          <Link href="/tickets" className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-linen-500 bg-linen-50 px-3 text-xs font-semibold text-ink-700 shadow-sm hover:bg-linen-200">
            All Tickets <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </div>
      </header>

      {bootstrapQuery.isError ? (
        <Alert
          variant="danger"
          title="Agent workspace identity could not be checked"
          action={<Button size="sm" variant="secondary" pending={bootstrapQuery.isFetching} pendingLabel="Retrying…" onClick={() => void bootstrapQuery.refetch()}>Retry</Button>}
        >
          Personal assignments remain available, but provider identity and team membership could not be refreshed.
        </Alert>
      ) : !bootstrapQuery.isLoading && bootstrapQuery.data && !bootstrapQuery.data.identity ? (
        <Alert variant="warning" title="Freshservice work identity not linked">
          Local assignments still appear in My Inbox. Ask an administrator to link your Freshservice agent identity to unlock authoritative personal and team queues.
        </Alert>
      ) : null}

      <section className="grid min-h-[680px] overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm lg:h-[calc(100vh-9rem)] lg:grid-cols-[14rem_22rem_minmax(0,1fr)]" aria-label="Agent ticket workspace">
        <aside className="min-w-0 border-b border-linen-400 bg-linen-100 lg:overflow-y-auto lg:border-b-0 lg:border-r" aria-label="Mailbox folders">
          <div className="border-b border-linen-300 p-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-400">My work</p>
            <p className="mt-1 break-words text-sm font-semibold text-ink-700 [overflow-wrap:anywhere]">{bootstrapQuery.data?.identity?.name || "Tickety assignments"}</p>
            {bootstrapQuery.data?.identity?.email && <p className="mt-0.5 break-words text-[11px] text-ink-400 [overflow-wrap:anywhere]">{bootstrapQuery.data.identity.email}</p>}
          </div>
          <nav className="grid grid-cols-2 gap-1 p-2 sm:grid-cols-3 lg:block" aria-label="Personal ticket folders">
            {MY_FOLDERS.map((item) => {
              const Icon = item.icon;
              const active = scope === "mine" && folder === item.id;
              const count = item.countKey ? bootstrapQuery.data?.counts[item.countKey] : undefined;
              return (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => selectMyFolder(item.id)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-10 w-full items-center gap-2 rounded-lg px-2.5 text-left text-xs font-medium transition-colors",
                    active ? "bg-white text-ink-700 shadow-sm ring-1 ring-linen-300" : "text-ink-500 hover:bg-white/70 hover:text-ink-700",
                  )}
                >
                  <Icon className={cn("h-3.5 w-3.5 shrink-0", active && "text-semantic-primary")} aria-hidden="true" />
                  <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">{item.label}</span>
                  {count != null && <span className="font-mono text-[10px] text-ink-400">{count}</span>}
                </button>
              );
            })}
          </nav>
          <div className="border-t border-linen-300 p-2">
            <div className="flex items-center gap-2 px-2.5 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-400">
              <Users className="h-3.5 w-3.5" aria-hidden="true" /> Team inboxes
            </div>
            {bootstrapQuery.isLoading ? (
              <div className="space-y-2 px-2"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>
            ) : bootstrapQuery.isError ? (
              <p className="px-2.5 py-3 text-xs leading-5 text-semantic-danger">Team inboxes could not be loaded. Retry the identity check above.</p>
            ) : !bootstrapQuery.data?.identity ? (
              <p className="px-2.5 py-3 text-xs leading-5 text-ink-400">Link a Freshservice work identity to load provider team inboxes.</p>
            ) : bootstrapQuery.data.teams.length ? (
              <div className="space-y-1">
                {bootstrapQuery.data.teams.map((team) => {
                  const active = scope === "team" && teamId === team.id;
                  return (
                    <div key={team.id} className={cn("rounded-lg", active && "bg-white shadow-sm ring-1 ring-linen-300")}>
                      <button type="button" onClick={() => selectTeam(team.id)} className="flex min-h-10 w-full items-center gap-2 rounded-lg px-2.5 text-left text-xs font-medium text-ink-600 hover:text-ink-700">
                        <Circle className={cn("h-2.5 w-2.5 shrink-0 fill-current", active ? "text-semantic-primary" : "text-ink-300")} aria-hidden="true" />
                        <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">{team.name}</span>
                        <span className="font-mono text-[10px] text-ink-400">{team.ticket_count}</span>
                      </button>
                      {active && team.unassigned_count > 0 && (
                        <button type="button" onClick={() => selectTeam(team.id, "unassigned")} className={cn("mb-1 ml-7 flex min-h-7 items-center gap-1.5 rounded-md px-2 text-[11px]", folder === "unassigned" ? "bg-[var(--color-warning-soft)] font-semibold text-semantic-warning" : "text-ink-400 hover:bg-linen-200")}>Unassigned <span className="font-mono">{team.unassigned_count}</span></button>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="px-2.5 py-3 text-xs leading-5 text-ink-400">No provider team memberships are available.</p>
            )}
          </div>
        </aside>

        <section className="min-w-0 border-b border-linen-400 bg-white lg:flex lg:min-h-0 lg:flex-col lg:border-b-0 lg:border-r" aria-labelledby="agent-ticket-list-title">
          <div className="border-b border-linen-300 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-semantic-primary">{scope === "mine" ? "Personal" : bootstrapQuery.data?.teams.find((team) => team.id === teamId)?.name || "Team"}</p>
                <h2 id="agent-ticket-list-title" className="break-words text-base font-semibold text-ink-700 [overflow-wrap:anywhere]">{folderLabel(folder, scope)}</h2>
              </div>
              <Badge variant="neutral">{tickets.length}{ticketsQuery.hasNextPage ? "+" : ""}</Badge>
            </div>
            {scope === "team" && teamId && (
              <div className="mt-3 flex gap-1 overflow-x-auto pb-1" aria-label="Team inbox filters">
                {TEAM_FOLDERS.map((item) => (
                  <button key={item.id} type="button" onClick={() => selectTeamFolder(item.id)} aria-pressed={folder === item.id} className={cn("min-h-7 shrink-0 rounded-md border px-2 text-[10px] font-semibold", folder === item.id ? "border-clay-200 bg-[var(--color-primary-soft)] text-semantic-primary" : "border-linen-300 bg-linen-100 text-ink-400 hover:text-ink-600")}>{item.label}</button>
                ))}
              </div>
            )}
            <div className="relative mt-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" aria-hidden="true" />
              <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} type="search" className="input-base h-9 pl-9 pr-8 text-xs" placeholder="Search this inbox" aria-label="Search current inbox" />
              {searchInput && <button type="button" onClick={() => setSearchInput("")} aria-label="Clear inbox search" className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-400 hover:bg-linen-200"><X className="h-3.5 w-3.5" /></button>}
            </div>
          </div>
          <div className="min-h-0 lg:flex-1 lg:overflow-y-auto" aria-live="polite">
            {ticketsQuery.isLoading ? (
              <div className="space-y-3 p-3" aria-label="Loading ticket inbox">{[1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-28" />)}</div>
            ) : ticketsQuery.isError && !ticketsQuery.data ? (
              <div className="p-4"><ErrorState density="compact" title="Inbox unavailable" description="This focused queue could not be loaded." actionLabel="Retry" onRetry={() => void ticketsQuery.refetch()} retrying={ticketsQuery.isFetching} /></div>
            ) : tickets.length === 0 ? (
              <EmptyState className="min-h-0 border-0 px-4 py-6 sm:min-h-40 lg:min-h-52" title="This folder is clear" description={searchInput.trim() ? "No tickets match this search." : "There are no tickets requiring attention in this view."} icon={<Check className="h-5 w-5" />} />
            ) : (
              <div>
                <div className="divide-y divide-linen-300">
                  {tickets.map((ticket) => <TicketRow key={ticket.id} ticket={ticket} selected={ticket.id === selected?.id} onSelect={() => replaceParams({ ticket: ticket.id })} onStar={() => stateMutation.mutate({ ticketId: ticket.id, update: { starred: !ticket.is_starred } })} />)}
                </div>
                {ticketsQuery.isFetchNextPageError && (
                  <div className="border-t border-linen-300 p-3"><Alert variant="danger" title="More tickets could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void ticketsQuery.fetchNextPage()}>Retry</Button>}>The tickets already shown remain available.</Alert></div>
                )}
                {ticketsQuery.hasNextPage && !ticketsQuery.isFetchNextPageError && (
                  <div className="border-t border-linen-300 p-3 text-center">
                    <Button variant="secondary" size="sm" pending={ticketsQuery.isFetchingNextPage} pendingLabel="Loading more…" onClick={() => void ticketsQuery.fetchNextPage()}>Load more tickets</Button>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        <section className="min-w-0 bg-linen-100 lg:min-h-0 lg:overflow-y-auto" aria-label="Ticket reading pane">
          {selected ? (
            <TicketReadingPane
              ticket={selected}
              copied={copied}
              onCopy={copyText}
              onStar={() => stateMutation.mutate({ ticketId: selected.id, update: { starred: !selected.is_starred } })}
              onFollowUp={() => stateMutation.mutate({ ticketId: selected.id, update: { follow_up_at: tomorrowAtNine() } })}
              onClearFollowUp={() => stateMutation.mutate({ ticketId: selected.id, update: { clear_follow_up: true } })}
              pending={stateMutation.isPending}
            />
          ) : deepLinkedTicketQuery.isLoading ? (
            <div className="space-y-4 p-4 sm:p-6" aria-label="Loading linked ticket" aria-busy="true"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-28 w-full" /><Skeleton className="h-48 w-full" /></div>
          ) : deepLinkedTicketQuery.isError ? (
            <div className="p-4 sm:p-6"><ErrorState title="Linked ticket unavailable" description="The selected ticket could not be restored from this inbox." actionLabel="Retry" onRetry={() => void deepLinkedTicketQuery.refetch()} retrying={deepLinkedTicketQuery.isFetching} /></div>
          ) : (
            <div className="grid min-h-0 place-items-center p-4 sm:min-h-48 lg:min-h-[24rem] lg:p-6"><EmptyState className="min-h-0 border-0 px-4 py-6 sm:min-h-40 lg:min-h-52" title="Select a ticket" description="Choose a ticket from the inbox to open the reading pane." icon={<ListFilter className="h-5 w-5" />} /></div>
          )}
        </section>
      </section>
    </PageFrame>
  );
}

function TicketRow({ ticket, selected, onSelect, onStar }: { ticket: AgentWorkspaceTicket; selected: boolean; onSelect: () => void; onStar: () => void }) {
  const deadline = activeDeadline(ticket);
  return (
    <article className={cn("group relative", selected ? "bg-[var(--color-primary-soft)]" : "bg-white hover:bg-linen-100")}>
      <button type="button" onClick={onSelect} className="w-full px-4 py-3.5 pr-11 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-clay-400" aria-current={selected ? "true" : undefined}>
        <div className="flex items-center gap-2 text-[10px] text-ink-400">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", ticket.is_unread ? "bg-semantic-primary" : "bg-transparent ring-1 ring-ink-300")} aria-label={ticket.is_unread ? "Unread" : "Read"} />
          <span className="min-w-0 flex-1 break-words font-semibold text-ink-500 [overflow-wrap:anywhere]">{requesterName(ticket)}</span>
          <time dateTime={ticketLastCommunicationAt(ticket) || undefined}>{formatTimeAgo(ticketLastCommunicationAt(ticket))}</time>
        </div>
        <h3 className={cn("mt-1.5 break-words text-sm leading-5 text-ink-700 [overflow-wrap:anywhere]", ticket.is_unread ? "font-semibold" : "font-medium")}>{ticket.subject}</h3>
        <TicketSentimentSubtitle ticket={ticket} />
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <TicketPriorityIndicator ticket={ticket} compact />
          {ticket.needs_reply && <span className="badge border-clay-200 bg-[var(--color-info-soft)] text-clay-700">Needs reply</span>}
          {ticket.sla_at_risk && <span className="badge border-rust-400/40 bg-[var(--color-danger-soft)] text-rust-600">SLA risk</span>}
          {deadline && <time className="ml-auto font-mono text-[10px] text-ink-400" dateTime={deadline}>{formatTimeAgo(deadline)}</time>}
        </div>
        {ticket.next_best_reasons[0] && <p className="mt-2 break-words text-[11px] leading-4 text-ink-400 [overflow-wrap:anywhere]">{ticket.next_best_reasons[0]}</p>}
      </button>
      <button type="button" onClick={onStar} aria-label={ticket.is_starred ? `Unstar ${ticket.subject}` : `Star ${ticket.subject}`} className={cn("absolute right-3 top-3 rounded-md p-1.5 transition-colors hover:bg-white", ticket.is_starred ? "text-amber-500" : "text-ink-300 opacity-70 group-hover:opacity-100")}>
        <Star className={cn("h-3.5 w-3.5", ticket.is_starred && "fill-current")} aria-hidden="true" />
      </button>
    </article>
  );
}

function TicketReadingPane({ ticket, copied, onCopy, onStar, onFollowUp, onClearFollowUp, pending }: {
  ticket: AgentWorkspaceTicket;
  copied: "reply" | "link" | null;
  onCopy: (value: string, kind: "reply" | "link") => void;
  onStar: () => void;
  onFollowUp: () => void;
  onClearFollowUp: () => void;
  pending: boolean;
}) {
  const sourceUrl = safeExternalUrl(ticket.external_url);
  const deadline = activeDeadline(ticket);
  const ticketHref = `/tickets/${encodeURIComponent(ticket.id)}`;
  return (
    <div className="space-y-4 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-ink-400">
            <span className="font-mono">#{ticket.external_id || ticket.id}</span>
            <ChevronRight className="h-3 w-3" aria-hidden="true" />
            <span>{ticket.assignment_scope === "mine" ? "My Inbox" : ticket.team_name || "Team Inbox"}</span>
          </div>
          <h2 className="mt-2 break-words text-xl font-semibold leading-7 tracking-[-0.02em] text-ink-700">{ticket.subject}</h2>
          <TicketSentimentSubtitle ticket={ticket} />
          <p className="mt-1 text-xs text-ink-400">{requesterName(ticket)} · updated {formatTimeAgo(ticketLastCommunicationAt(ticket))}</p>
        </div>
        <IconButton size="sm" variant="secondary" onClick={onStar} aria-label={ticket.is_starred ? "Remove star" : "Star ticket"} icon={<Star className={cn("h-4 w-4", ticket.is_starred && "fill-current text-amber-500")} />} />
      </div>

      <div className="flex flex-wrap gap-2">
        <TicketPriorityIndicator ticket={ticket} />
        <span className={cn("badge", statusColor(ticket.status))}>{ticket.status}</span>
        {ticket.needs_reply && <Badge variant="info" icon={<MessageCircleReply className="h-3 w-3" />}>Requester waiting</Badge>}
        {ticket.sla_at_risk && <Badge variant="danger" icon={<BellRing className="h-3 w-3" />}>SLA at risk</Badge>}
      </div>

      <section className="rounded-xl border border-clay-200 bg-gradient-to-br from-[var(--color-primary-soft)] to-white p-4" aria-labelledby="next-best-action-title">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-semantic-primary">Next best action</p>
            <h3 id="next-best-action-title" className="mt-0.5 text-sm font-semibold text-ink-700">Focus score {ticket.next_best_score}/100</h3>
          </div>
          <Sparkles className="h-5 w-5 text-semantic-primary" aria-hidden="true" />
        </div>
        {ticket.next_best_reasons.length ? <ul className="mt-3 space-y-1.5">{ticket.next_best_reasons.map((reason) => <li key={reason} className="flex gap-2 text-xs leading-5 text-ink-600"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-primary" aria-hidden="true" />{reason}</li>)}</ul> : <p className="mt-2 text-xs text-ink-500">This ticket is ordered by activity, SLA, and priority.</p>}
        {deadline && <p className="mt-3 flex items-center gap-1.5 border-t border-clay-200 pt-3 text-[11px] text-ink-500"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" /> Active SLA: {formatOperationalTimestamp(deadline)}</p>}
      </section>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" leadingIcon={<AlarmClock className="h-3.5 w-3.5" />} pending={pending} pendingLabel="Saving…" onClick={ticket.follow_up_at ? onClearFollowUp : onFollowUp}>{ticket.follow_up_at ? "Clear follow-up" : "Follow up tomorrow"}</Button>
        <Button size="sm" variant="ghost" leadingIcon={copied === "link" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} onClick={() => onCopy(`${window.location.origin}${ticketHref}`, "link")}>{copied === "link" ? "Link copied" : "Copy link"}</Button>
        <Link href={ticketHref} className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-3 text-xs font-semibold text-semantic-primary hover:bg-white">Full workbench <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
        {sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-3 text-xs font-semibold text-ink-500 hover:bg-white">Freshservice <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" /></a>}
      </div>

      {ticket.follow_up_at && <Alert variant="info" title="Follow-up scheduled">This ticket will appear in Follow up at {formatOperationalTimestamp(ticket.follow_up_at)}.</Alert>}

      <section className="rounded-xl border border-linen-300 bg-white p-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-400">Ticket brief</p>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-600">{ticket.summary || ticket.description || "No description is available."}</p>
      </section>

      {ticket.suggested_response && (
        <section className="rounded-xl border border-linen-300 bg-white p-4" aria-labelledby="suggested-reply-title">
          <div className="flex items-center justify-between gap-2">
            <div><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-semantic-primary">Draft accelerator</p><h3 id="suggested-reply-title" className="mt-0.5 text-sm font-semibold text-ink-700">Suggested response</h3></div>
            <Button size="sm" variant="ghost" leadingIcon={copied === "reply" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} onClick={() => onCopy(ticket.suggested_response || "", "reply")}>{copied === "reply" ? "Copied" : "Copy draft"}</Button>
          </div>
          <p className="mt-3 whitespace-pre-wrap text-xs leading-5 text-ink-600">{ticket.suggested_response}</p>
          <p className="mt-3 text-[10px] text-ink-400">Review before using. Replies remain managed in Freshservice.</p>
        </section>
      )}

      {ticket.external_source === "freshservice" ? <FreshserviceConversationThread ticket={ticket} /> : (
        <section className="rounded-xl border border-linen-300 bg-white p-4"><p className="text-sm leading-6 text-ink-600">{ticket.description}</p></section>
      )}
    </div>
  );
}
