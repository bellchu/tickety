"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Problem, UserOut, Ticket } from "@/lib/types";
import {
  AlertOctagon,
  Plus,
  RefreshCw,
  X,
  Trash2,
  Link,
  Unlink,
  Search,
  Filter,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { priorityColor, statusColor, formatTimeAgo } from "@/lib/utils";

const PROBLEM_STATUS_FILTERS = [
  { value: "", label: "All Statuses" },
  { value: "New", label: "New" },
  { value: "Under Investigation", label: "Under Investigation" },
  { value: "Known Error", label: "Known Error" },
  { value: "Resolved", label: "Resolved" },
  { value: "Closed", label: "Closed" },
];

const PRIORITY_OPTIONS = ["P1", "P2", "P3", "P4"];

export default function ProblemsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Problem | null>(null);
  const [viewing, setViewing] = useState<Problem | null>(null);

  const { data: problems, isLoading } = useQuery({
    queryKey: ["problems", statusFilter],
    queryFn: () => api.getProblems(statusFilter || undefined),
  });
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: api.getUsers });

  const createMut = useMutation({
    mutationFn: (payload: {
      title: string;
      description?: string;
      priority?: string;
      category?: string;
      assigned_to?: string;
      impact_scope?: string;
    }) => api.createProblem(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["problems"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: Partial<Problem>;
    }) => api.updateProblem(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["problems"] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteProblem(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["problems"] }),
  });

  const filtered = (problems || []).filter(
    (p) =>
      p.title.toLowerCase().includes(search.toLowerCase()) ||
      (p.description || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Problem Management</h1>
          <p className="text-[13px] text-ink-500">
            {(problems || []).length} problems · root cause analysis and resolution
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Filter className="w-3.5 h-3.5 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="input-base pl-9 text-xs w-44"
            >
              {PROBLEM_STATUS_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search problems…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input-base pl-9 text-xs w-48"
            />
          </div>
          <button
            onClick={() => setShowForm(true)}
            className="btn-primary text-xs"
          >
            <Plus className="w-4 h-4" strokeWidth={1.5} />
            New Problem
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="card-surface p-6 space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton h-12 w-full" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card-surface p-12 text-center">
          <AlertOctagon className="w-10 h-10 text-ink-300 mx-auto mb-3" />
          <p className="text-ink-500 text-sm font-medium">No problems found</p>
          <p className="text-ink-400 text-xs mt-1">
            {statusFilter
              ? "Try changing the status filter"
              : "Create a new problem record to get started"}
          </p>
        </div>
      ) : (
        <div className="card-surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-300 bg-linen-100">
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Title
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Priority
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Category
                </th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Linked
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Assigned To
                </th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr
                  key={p.id}
                  className="border-b border-linen-200 last:border-0 hover:bg-linen-100 cursor-pointer"
                  onClick={() => setViewing(p)}
                >
                  <td className="px-4 py-3 text-xs text-ink-400 font-mono">
                    {p.id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 font-medium text-ink-700 max-w-xs truncate">
                    {p.title}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                        statusColor(p.status)
                      )}
                    >
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {p.priority ? (
                      <span
                        className={cn(
                          "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                          priorityColor(p.priority)
                        )}
                      >
                        {p.priority}
                      </span>
                    ) : (
                      <span className="text-ink-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-ink-500 text-xs">
                    {p.category || "—"}
                  </td>
                  <td className="px-4 py-3 text-center tabular-nums text-xs text-ink-600">
                    {p.linked_tickets_count}
                  </td>
                  <td className="px-4 py-3 text-ink-500 text-xs">
                    {p.assigned_name || "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div
                      className="inline-flex items-center gap-1"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        onClick={() => setViewing(p)}
                        className="p-1.5 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200"
                        title="View"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setEditing(p)}
                        className="p-1.5 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200"
                        title="Edit"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => {
                          if (
                            window.confirm("Delete this problem record?")
                          )
                            deleteMut.mutate(p.id);
                        }}
                        className="p-1.5 rounded text-ink-400 hover:text-rust-500 hover:bg-rust-400/10"
                        title="Delete"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(showForm || editing) && (
        <ProblemFormModal
          problem={editing}
          users={users || []}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
          }}
          onSubmit={(payload) => {
            if (editing) {
              updateMut.mutate({ id: editing.id, payload });
            } else {
              createMut.mutate(payload);
            }
          }}
          loading={createMut.isPending || updateMut.isPending}
          error={createMut.error || updateMut.error}
        />
      )}

      {viewing && (
        <ProblemDetailModal
          problem={viewing}
          users={users || []}
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  );
}

function ProblemFormModal({
  problem,
  users,
  onClose,
  onSubmit,
  loading,
  error,
}: {
  problem: Problem | null;
  users: UserOut[];
  onClose: () => void;
  onSubmit: (payload: {
    title: string;
    description?: string;
    priority?: string;
    category?: string;
    assigned_to?: string;
    impact_scope?: string;
  }) => void;
  loading: boolean;
  error: unknown;
}) {
  const [title, setTitle] = useState(problem?.title || "");
  const [description, setDescription] = useState(problem?.description || "");
  const [priority, setPriority] = useState(problem?.priority || "");
  const [category, setCategory] = useState(problem?.category || "");
  const [assignedTo, setAssignedTo] = useState(problem?.assigned_to || "");
  const [impactScope, setImpactScope] = useState(problem?.impact_scope || "");

  const errorMsg =
    error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="card-surface w-full max-w-lg p-6 space-y-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl text-ink-700">
            {problem ? "Edit Problem" : "New Problem"}
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded text-ink-400 hover:bg-linen-200"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Title *</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input-base"
              placeholder="Problem title"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">
              Description
            </span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input-base min-h-[80px]"
              placeholder="Describe the problem…"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Priority</span>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="input-base"
              >
                <option value="">—</option>
                {PRIORITY_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Category</span>
              <input
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="input-base"
                placeholder="e.g. Network"
              />
            </label>
          </div>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Assignee</span>
            <select
              value={assignedTo}
              onChange={(e) => setAssignedTo(e.target.value)}
              className="input-base"
            >
              <option value="">Unassigned</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">
              Impact Scope
            </span>
            <textarea
              value={impactScope}
              onChange={(e) => setImpactScope(e.target.value)}
              className="input-base min-h-[60px]"
              placeholder="Describe the impact scope…"
            />
          </label>
        </div>
        {errorMsg && (
          <p className="text-xs text-rust-500">Failed: {errorMsg}</p>
        )}
        <div className="flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200"
          >
            Cancel
          </button>
          <button
            onClick={() =>
              onSubmit({
                title,
                description: description || undefined,
                priority: priority || undefined,
                category: category || undefined,
                assigned_to: assignedTo || undefined,
                impact_scope: impactScope || undefined,
              })
            }
            disabled={loading || !title.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
            {problem ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ProblemDetailModal({
  problem,
  users,
  onClose,
}: {
  problem: Problem;
  users: UserOut[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [linkTicketId, setLinkTicketId] = useState("");

  const { data: fullProblem } = useQuery({
    queryKey: ["problem", problem.id],
    queryFn: () => api.getProblem(problem.id),
    initialData: problem,
  });

  const { data: linkedTickets, isLoading: ticketsLoading } = useQuery({
    queryKey: ["problem-tickets", problem.id],
    queryFn: () => api.getProblemTickets(problem.id),
  });

  const linkMut = useMutation({
    mutationFn: ({
      problemId,
      ticketId,
    }: {
      problemId: string;
      ticketId: string;
    }) => api.linkTicketToProblem(problemId, ticketId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["problem-tickets", problem.id] });
      queryClient.invalidateQueries({ queryKey: ["problems"] });
      setLinkTicketId("");
    },
  });

  const unlinkMut = useMutation({
    mutationFn: ({
      problemId,
      ticketId,
    }: {
      problemId: string;
      ticketId: string;
    }) => api.unlinkTicketFromProblem(problemId, ticketId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["problem-tickets", problem.id] });
      queryClient.invalidateQueries({ queryKey: ["problems"] });
    },
  });

  const p = fullProblem;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="card-surface w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div className="space-y-1 min-w-0">
            <h2 className="font-serif text-xl text-ink-700">{p.title}</h2>
            <p className="text-xs text-ink-400 font-mono">{p.id}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-ink-400 hover:bg-linen-200 shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Status</p>
            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                statusColor(p.status)
              )}
            >
              {p.status}
            </span>
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Priority</p>
            {p.priority ? (
              <span
                className={cn(
                  "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                  priorityColor(p.priority)
                )}
              >
                {p.priority}
              </span>
            ) : (
              <span className="text-xs text-ink-300">—</span>
            )}
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Category</p>
            <p className="text-sm text-ink-700">{p.category || "—"}</p>
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Assigned To</p>
            <p className="text-sm text-ink-700">{p.assigned_name || "—"}</p>
          </div>
        </div>

        {p.description && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Description</p>
            <p className="text-sm text-ink-600 whitespace-pre-wrap">
              {p.description}
            </p>
          </div>
        )}

        {p.impact_scope && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Impact Scope</p>
            <p className="text-sm text-ink-600 whitespace-pre-wrap">
              {p.impact_scope}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4">
          {p.root_cause && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-ink-400">Root Cause</p>
              <p className="text-sm text-ink-600 whitespace-pre-wrap">
                {p.root_cause}
              </p>
            </div>
          )}
          {p.workaround && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-ink-400">Workaround</p>
              <p className="text-sm text-ink-600 whitespace-pre-wrap">
                {p.workaround}
              </p>
            </div>
          )}
          {p.resolution && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-ink-400">Resolution</p>
              <p className="text-sm text-ink-600 whitespace-pre-wrap">
                {p.resolution}
              </p>
            </div>
          )}
        </div>

        <div className="border-t border-linen-200 pt-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-ink-700">
              Linked Tickets
              {linkedTickets && (
                <span className="text-ink-400 font-normal ml-1">
                  ({linkedTickets.length})
                </span>
              )}
            </h3>
            <div className="flex items-center gap-1.5">
              <input
                type="text"
                value={linkTicketId}
                onChange={(e) => setLinkTicketId(e.target.value)}
                placeholder="Ticket ID"
                className="input-base text-xs w-36 h-7"
              />
              <button
                onClick={() =>
                  linkMut.mutate({
                    problemId: problem.id,
                    ticketId: linkTicketId.trim(),
                  })
                }
                disabled={!linkTicketId.trim() || linkMut.isPending}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-semibold bg-moss-400/15 text-moss-600 hover:bg-moss-400/25 disabled:opacity-50"
              >
                {linkMut.isPending ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : (
                  <Link className="w-3 h-3" />
                )}
                Link
              </button>
            </div>
          </div>

          {linkMut.error && (
            <p className="text-xs text-rust-500 mb-2">
              Link failed:{" "}
              {linkMut.error instanceof Error
                ? linkMut.error.message
                : String(linkMut.error)}
            </p>
          )}

          {ticketsLoading ? (
            <div className="space-y-2">
              {[1, 2].map((i) => (
                <div key={i} className="skeleton h-8 w-full" />
              ))}
            </div>
          ) : linkedTickets && linkedTickets.length > 0 ? (
            <div className="space-y-1">
              {linkedTickets.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-linen-100"
                >
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-ink-700 truncate">
                      {t.subject}
                    </p>
                    <p className="text-[11px] text-ink-400 font-mono">
                      {t.id}
                    </p>
                  </div>
                  <button
                    onClick={() =>
                      unlinkMut.mutate({
                        problemId: problem.id,
                        ticketId: t.id,
                      })
                    }
                    className="p-1 rounded text-ink-400 hover:text-rust-500 hover:bg-rust-400/10"
                    title="Unlink"
                  >
                    <Unlink className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-ink-400 text-center py-4">
              No tickets linked yet
            </p>
          )}
        </div>

        <div className="text-xs text-ink-400 flex items-center gap-4">
          {p.created_at && <span>Created {formatTimeAgo(p.created_at)}</span>}
          {p.updated_at && <span>Updated {formatTimeAgo(p.updated_at)}</span>}
          {p.closed_at && <span>Closed {formatTimeAgo(p.closed_at)}</span>}
        </div>
      </div>
    </div>
  );
}
