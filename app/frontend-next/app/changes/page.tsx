"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ChangeRecord, ChangeApproval, UserOut } from "@/lib/types";
import {
  GitBranch,
  Plus,
  RefreshCw,
  X,
  Trash2,
  Search,
  Filter,
  Eye,
  AlertTriangle,
  CheckCircle2,
  Clock,
  UserPlus,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { priorityColor, formatTimeAgo } from "@/lib/utils";

const CHANGE_STATUS_FILTERS = [
  { value: "", label: "All Statuses" },
  { value: "Draft", label: "Draft" },
  { value: "Submitted", label: "Submitted" },
  { value: "Approved", label: "Approved" },
  { value: "In Progress", label: "In Progress" },
  { value: "Completed", label: "Completed" },
  { value: "Rejected", label: "Rejected" },
  { value: "Cancelled", label: "Cancelled" },
];

const CHANGE_TYPES = ["Normal", "Standard", "Emergency"];
const RISK_LEVELS = ["Low", "Medium", "High"];
const PRIORITY_OPTIONS = ["P1", "P2", "P3", "P4"];

const CHANGE_STATUS_COLORS: Record<string, string> = {
  Draft: "text-ink-500 bg-linen-300 border-linen-400",
  Submitted: "text-clay-500 bg-clay-400/10 border-clay-400/30",
  Approved: "text-moss-600 bg-moss-500/10 border-moss-500/30",
  "In Progress": "text-blue-500 bg-blue-400/10 border-blue-400/30",
  Completed: "text-moss-600 bg-moss-500/15 border-moss-500/40",
  Rejected: "text-rust-500 bg-rust-400/10 border-rust-400/30",
  Cancelled: "text-ink-400 bg-linen-300 border-linen-400",
};

const RISK_COLORS: Record<string, string> = {
  Low: "text-moss-600 bg-moss-500/10 border-moss-500/30",
  Medium: "text-amber-600 bg-amber-400/10 border-amber-400/30",
  High: "text-rust-500 bg-rust-400/10 border-rust-400/30",
};

const TYPE_COLORS: Record<string, string> = {
  Normal: "text-blue-500 bg-blue-400/10 border-blue-400/30",
  Standard: "text-moss-600 bg-moss-500/10 border-moss-500/30",
  Emergency: "text-rust-500 bg-rust-400/10 border-rust-400/30",
};

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ChangesPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ChangeRecord | null>(null);
  const [viewing, setViewing] = useState<ChangeRecord | null>(null);

  const { data: changes, isLoading } = useQuery({
    queryKey: ["changes", statusFilter],
    queryFn: () => api.getChanges(statusFilter || undefined),
  });
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: api.getUsers });

  const createMut = useMutation({
    mutationFn: (payload: Partial<ChangeRecord>) => api.createChange(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["changes"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: Partial<ChangeRecord>;
    }) => api.updateChange(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["changes"] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteChange(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["changes"] }),
  });

  const filtered = (changes || []).filter(
    (c) =>
      c.title.toLowerCase().includes(search.toLowerCase()) ||
      (c.description || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Change Management</h1>
          <p className="text-[13px] text-ink-500">
            {(changes || []).length} changes · plan, review, and deploy
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
              {CHANGE_STATUS_FILTERS.map((f) => (
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
              placeholder="Search changes…"
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
            New Change
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
          <GitBranch className="w-10 h-10 text-ink-300 mx-auto mb-3" />
          <p className="text-ink-500 text-sm font-medium">No changes found</p>
          <p className="text-ink-400 text-xs mt-1">
            {statusFilter
              ? "Try changing the status filter"
              : "Create a new change request to get started"}
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
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Risk
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Priority
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Scheduled
                </th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-linen-200 last:border-0 hover:bg-linen-100 cursor-pointer"
                  onClick={() => setViewing(c)}
                >
                  <td className="px-4 py-3 text-xs text-ink-400 font-mono">
                    {c.id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 font-medium text-ink-700 max-w-xs truncate">
                    {c.title}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                        TYPE_COLORS[c.change_type] || TYPE_COLORS.Normal
                      )}
                    >
                      {c.change_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                        CHANGE_STATUS_COLORS[c.status] ||
                          CHANGE_STATUS_COLORS.Draft
                      )}
                    >
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                        RISK_COLORS[c.risk_level] || RISK_COLORS.Medium
                      )}
                    >
                      {c.risk_level}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {c.priority ? (
                      <span
                        className={cn(
                          "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                          priorityColor(c.priority)
                        )}
                      >
                        {c.priority}
                      </span>
                    ) : (
                      <span className="text-ink-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-ink-500 text-xs">
                    {formatDate(c.scheduled_start)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div
                      className="inline-flex items-center gap-1"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        onClick={() => setViewing(c)}
                        className="p-1.5 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200"
                        title="View"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setEditing(c)}
                        className="p-1.5 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200"
                        title="Edit"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => {
                          if (
                            window.confirm("Delete this change record?")
                          )
                            deleteMut.mutate(c.id);
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
        <ChangeFormModal
          change={editing}
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
        <ChangeDetailModal
          change={viewing}
          users={users || []}
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  );
}

function ChangeFormModal({
  change,
  users,
  onClose,
  onSubmit,
  loading,
  error,
}: {
  change: ChangeRecord | null;
  users: UserOut[];
  onClose: () => void;
  onSubmit: (payload: Partial<ChangeRecord>) => void;
  loading: boolean;
  error: unknown;
}) {
  const [title, setTitle] = useState(change?.title || "");
  const [description, setDescription] = useState(change?.description || "");
  const [changeType, setChangeType] = useState(change?.change_type || "Normal");
  const [priority, setPriority] = useState(change?.priority || "");
  const [riskLevel, setRiskLevel] = useState(change?.risk_level || "Low");
  const [impact, setImpact] = useState(change?.impact || "");
  const [rollbackPlan, setRollbackPlan] = useState(
    change?.rollback_plan || ""
  );
  const [testPlan, setTestPlan] = useState(change?.test_plan || "");
  const [scheduledStart, setScheduledStart] = useState(
    change?.scheduled_start
      ? change.scheduled_start.slice(0, 16)
      : ""
  );
  const [scheduledEnd, setScheduledEnd] = useState(
    change?.scheduled_end ? change.scheduled_end.slice(0, 16) : ""
  );
  const [assignedTo, setAssignedTo] = useState(change?.assigned_to || "");

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
            {change ? "Edit Change" : "New Change"}
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
              placeholder="Change title"
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
              placeholder="Describe the change…"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">
                Change Type
              </span>
              <select
                value={changeType}
                onChange={(e) => setChangeType(e.target.value)}
                className="input-base"
              >
                {CHANGE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
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
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">
                Risk Level
              </span>
              <select
                value={riskLevel}
                onChange={(e) => setRiskLevel(e.target.value)}
                className="input-base"
              >
                {RISK_LEVELS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
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
          </div>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Impact</span>
            <textarea
              value={impact}
              onChange={(e) => setImpact(e.target.value)}
              className="input-base min-h-[60px]"
              placeholder="Describe the impact…"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">
              Rollback Plan
            </span>
            <textarea
              value={rollbackPlan}
              onChange={(e) => setRollbackPlan(e.target.value)}
              className="input-base min-h-[60px]"
              placeholder="Steps to rollback if needed…"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Test Plan</span>
            <textarea
              value={testPlan}
              onChange={(e) => setTestPlan(e.target.value)}
              className="input-base min-h-[60px]"
              placeholder="How will you test this change…"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">
                Scheduled Start
              </span>
              <input
                type="datetime-local"
                value={scheduledStart}
                onChange={(e) => setScheduledStart(e.target.value)}
                className="input-base"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">
                Scheduled End
              </span>
              <input
                type="datetime-local"
                value={scheduledEnd}
                onChange={(e) => setScheduledEnd(e.target.value)}
                className="input-base"
              />
            </label>
          </div>
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
                change_type: changeType,
                priority: priority || undefined,
                risk_level: riskLevel,
                impact: impact || undefined,
                rollback_plan: rollbackPlan || undefined,
                test_plan: testPlan || undefined,
                scheduled_start: scheduledStart
                  ? new Date(scheduledStart).toISOString()
                  : undefined,
                scheduled_end: scheduledEnd
                  ? new Date(scheduledEnd).toISOString()
                  : undefined,
                assigned_to: assignedTo || undefined,
              })
            }
            disabled={loading || !title.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
            {change ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ChangeDetailModal({
  change,
  users,
  onClose,
}: {
  change: ChangeRecord;
  users: UserOut[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [approverId, setApproverId] = useState("");

  const { data: fullChange } = useQuery({
    queryKey: ["change", change.id],
    queryFn: () => api.getChange(change.id),
    initialData: change,
  });

  const { data: approvals, isLoading: approvalsLoading } = useQuery({
    queryKey: ["change-approvals", change.id],
    queryFn: () => api.getChangeApprovals(change.id),
  });

  const addApprovalMut = useMutation({
    mutationFn: ({
      changeId,
      approverId,
    }: {
      changeId: string;
      approverId: string;
    }) => api.addChangeApproval(changeId, approverId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["change-approvals", change.id],
      });
      setApproverId("");
    },
  });

  const decideMut = useMutation({
    mutationFn: ({
      approvalId,
      decision,
      comment,
    }: {
      approvalId: number;
      decision: string;
      comment?: string;
    }) =>
      api.decideApproval(change.id, String(approvalId), decision, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["change-approvals", change.id],
      });
    },
  });

  const c = fullChange;

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
            <h2 className="font-serif text-xl text-ink-700">{c.title}</h2>
            <p className="text-xs text-ink-400 font-mono">{c.id}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-ink-400 hover:bg-linen-200 shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Status</p>
            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                CHANGE_STATUS_COLORS[c.status] || CHANGE_STATUS_COLORS.Draft
              )}
            >
              {c.status}
            </span>
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Type</p>
            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                TYPE_COLORS[c.change_type] || TYPE_COLORS.Normal
              )}
            >
              {c.change_type}
            </span>
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Risk</p>
            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                RISK_COLORS[c.risk_level] || RISK_COLORS.Medium
              )}
            >
              {c.risk_level}
            </span>
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Priority</p>
            {c.priority ? (
              <span
                className={cn(
                  "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                  priorityColor(c.priority)
                )}
              >
                {c.priority}
              </span>
            ) : (
              <span className="text-xs text-ink-300">—</span>
            )}
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Assigned To</p>
            <p className="text-sm text-ink-700">{c.assigned_name || "—"}</p>
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Requested By</p>
            <p className="text-sm text-ink-700">{c.requested_name || "—"}</p>
          </div>
        </div>

        {c.description && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Description</p>
            <p className="text-sm text-ink-600 whitespace-pre-wrap">
              {c.description}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {c.impact && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-ink-400">Impact</p>
              <p className="text-sm text-ink-600 whitespace-pre-wrap">
                {c.impact}
              </p>
            </div>
          )}
          {c.rollback_plan && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-ink-400">
                Rollback Plan
              </p>
              <p className="text-sm text-ink-600 whitespace-pre-wrap">
                {c.rollback_plan}
              </p>
            </div>
          )}
          {c.test_plan && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-ink-400">Test Plan</p>
              <p className="text-sm text-ink-600 whitespace-pre-wrap">
                {c.test_plan}
              </p>
            </div>
          )}
          <div className="space-y-1">
            <p className="text-xs font-medium text-ink-400">Schedule</p>
            <p className="text-sm text-ink-600">
              {c.scheduled_start
                ? formatDate(c.scheduled_start)
                : "—"}{" "}
              →{" "}
              {c.scheduled_end ? formatDate(c.scheduled_end) : "—"}
            </p>
          </div>
        </div>

        <div className="border-t border-linen-200 pt-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-ink-700">
              Approvals
              {approvals && (
                <span className="text-ink-400 font-normal ml-1">
                  ({approvals.length})
                </span>
              )}
            </h3>
            <div className="flex items-center gap-1.5">
              <select
                value={approverId}
                onChange={(e) => setApproverId(e.target.value)}
                className="input-base text-xs w-36 h-7"
              >
                <option value="">Select approver</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
              <button
                onClick={() =>
                  addApprovalMut.mutate({
                    changeId: change.id,
                    approverId,
                  })
                }
                disabled={!approverId || addApprovalMut.isPending}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-semibold bg-moss-400/15 text-moss-600 hover:bg-moss-400/25 disabled:opacity-50"
              >
                {addApprovalMut.isPending ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : (
                  <UserPlus className="w-3 h-3" />
                )}
                Add
              </button>
            </div>
          </div>

          {addApprovalMut.error && (
            <p className="text-xs text-rust-500 mb-2">
              Failed:{" "}
              {addApprovalMut.error instanceof Error
                ? addApprovalMut.error.message
                : String(addApprovalMut.error)}
            </p>
          )}

          {approvalsLoading ? (
            <div className="space-y-2">
              {[1, 2].map((i) => (
                <div key={i} className="skeleton h-10 w-full" />
              ))}
            </div>
          ) : approvals && approvals.length > 0 ? (
            <div className="space-y-2">
              {approvals.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-linen-100"
                >
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-ink-700">
                      {a.approver_name || a.approver_id}
                    </p>
                    {a.decision ? (
                      <div className="flex items-center gap-1 mt-0.5">
                        <span
                          className={cn(
                            "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border",
                            a.decision === "approved"
                              ? "text-moss-600 bg-moss-500/10 border-moss-500/30"
                              : "text-rust-500 bg-rust-400/10 border-rust-400/30"
                          )}
                        >
                          {a.decision}
                        </span>
                        {a.comment && (
                          <span className="text-[11px] text-ink-400 truncate max-w-[200px]">
                            — {a.comment}
                          </span>
                        )}
                      </div>
                    ) : (
                      <p className="text-[11px] text-ink-400 mt-0.5">
                        Pending decision
                      </p>
                    )}
                  </div>
                  {!a.decision && (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() =>
                          decideMut.mutate({
                            approvalId: a.id,
                            decision: "approved",
                          })
                        }
                        className="p-1 rounded text-moss-500 hover:bg-moss-400/15"
                        title="Approve"
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() =>
                          decideMut.mutate({
                            approvalId: a.id,
                            decision: "rejected",
                          })
                        }
                        className="p-1 rounded text-rust-500 hover:bg-rust-400/15"
                        title="Reject"
                      >
                        <ThumbsDown className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-ink-400 text-center py-4">
              No approvals yet
            </p>
          )}
        </div>

        <div className="text-xs text-ink-400 flex items-center gap-4">
          {c.created_at && <span>Created {formatTimeAgo(c.created_at)}</span>}
          {c.updated_at && <span>Updated {formatTimeAgo(c.updated_at)}</span>}
          {c.completed_at && (
            <span>Completed {formatTimeAgo(c.completed_at)}</span>
          )}
        </div>
      </div>
    </div>
  );
}
