"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { UserOut, UserCreateInput } from "@/lib/types";
import {
  Users, Plus, RefreshCw, ShieldCheck, UserCog, Trash2, X, Search,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ROLES = [
  { value: "admin", label: "Admin", icon: ShieldCheck, desc: "Full access — manage all settings and users" },
  { value: "supervisor", label: "Supervisor", icon: UserCog, desc: "Manage tickets, agents, and view reports" },
  { value: "agent", label: "Agent", icon: Users, desc: "Handle assigned tickets and update status" },
];

const ROLE_COLORS: Record<string, string> = {
  admin: "bg-rust-400/15 text-rust-500 border-rust-400/30",
  supervisor: "bg-amber-400/15 text-amber-600 border-amber-400/30",
  agent: "bg-moss-400/15 text-moss-600 border-moss-400/30",
};

export default function AgentsPage() {
  const queryClient = useQueryClient();
  const { data: users, isLoading } = useQuery({ queryKey: ["users"], queryFn: api.getUsers });
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [search, setSearch] = useState("");

  const createMut = useMutation({
    mutationFn: (payload: UserCreateInput) => api.createUser(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<UserCreateInput> }) => api.updateUser(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setEditing(null);
    },
  });

  const deactivateMut = useMutation({
    mutationFn: (id: string) => api.deleteUser(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const activeUsers = (users || []).filter((u) => u.is_active);
  const filtered = activeUsers.filter(
    (u) => u.name.toLowerCase().includes(search.toLowerCase()) || (u.email || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Agents</h1>
          <p className="text-[13px] text-ink-500">
            {activeUsers.length} active agents · manage roles and access
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search agents…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input-base pl-9 text-xs w-48"
            />
          </div>
          <button onClick={() => setShowForm(true)} className="btn-primary text-xs">
            <Plus className="w-4 h-4" strokeWidth={1.5} />
            Add Agent
          </button>
        </div>
      </div>

      {/* Role legend */}
      <div className="grid grid-cols-3 gap-4">
        {ROLES.map((r) => {
          const Icon = r.icon;
          const count = activeUsers.filter((u) => u.role === r.value).length;
          return (
            <div key={r.value} className="card-surface p-4 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-linen-300 flex items-center justify-center shrink-0">
                <Icon className="w-4 h-4 text-ink-600" strokeWidth={1.5} />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink-700">{r.label}</p>
                <p className="text-xs text-ink-400 truncate">{r.desc}</p>
                <p className="text-xs text-ink-500 mt-0.5">{count} assigned</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Agents table */}
      {isLoading ? (
        <div className="card-surface p-6 space-y-3">{[1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-12 w-full" />)}</div>
      ) : (
        <div className="card-surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-300 bg-linen-100">
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Agent</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Role</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Title</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">Impact</th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">Tier</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((u) => (
                <tr key={u.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-clay-400/15 text-clay-500 flex items-center justify-center text-xs font-semibold shrink-0">
                        {u.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium text-ink-700">{u.name}</p>
                        <p className="text-xs text-ink-400">{u.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border", ROLE_COLORS[u.role] || ROLE_COLORS.agent)}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-500">{u.title || "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums font-medium text-ink-600">{u.impact_points.toLocaleString()}</td>
                  <td className="px-4 py-3 text-center">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border border-linen-400 text-ink-600">T{u.tier}</span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button onClick={() => setEditing(u)} className="p-1.5 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200" title="Edit">
                        <UserCog className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => deactivateMut.mutate(u.id)} className="p-1.5 rounded text-ink-400 hover:text-rust-500 hover:bg-rust-400/10" title="Deactivate">
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

      {/* Create / Edit modal */}
      {(showForm || editing) && (
        <UserFormModal
          user={editing}
          onClose={() => { setShowForm(false); setEditing(null); }}
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
    </div>
  );
}

function UserFormModal({ user, onClose, onSubmit, loading, error }: {
  user: UserOut | null;
  onClose: () => void;
  onSubmit: (payload: UserCreateInput) => void;
  loading: boolean;
  error: unknown;
}) {
  const [name, setName] = useState(user?.name || "");
  const [email, setEmail] = useState(user?.email || "");
  const [title, setTitle] = useState(user?.title || "");
  const [role, setRole] = useState(user?.role || "agent");
  const [password, setPassword] = useState("");

  const errorMsg = error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm" onClick={onClose}>
      <div className="card-surface w-full max-w-md p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl text-ink-700">{user ? "Edit Agent" : "Add Agent"}</h2>
          <button onClick={onClose} className="p-1 rounded text-ink-400 hover:bg-linen-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className="input-base" placeholder="Jane Doe" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="input-base" placeholder="jane@company.com" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} className="input-base" placeholder="Support Engineer" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Role</span>
            <select value={role} onChange={(e) => setRole(e.target.value)} className="input-base">
              {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">
              {user ? "New Password (leave blank to keep)" : "Password (auto-generated if blank)"}
            </span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="input-base" placeholder="••••••" />
          </label>
        </div>
        {errorMsg && <p className="text-xs text-rust-500">Failed: {errorMsg}</p>}
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200">Cancel</button>
          <button
            onClick={() => onSubmit({ name, email, title: title || undefined, role, password: password || undefined })}
            disabled={loading || !name.trim() || !email.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
            {user ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}