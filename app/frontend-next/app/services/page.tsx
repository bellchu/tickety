"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ServiceItem } from "@/lib/types";
import {
  Package, ShoppingCart, Plus, RefreshCw, Search, X, Trash2, Edit3,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function ServicesPage() {
  const queryClient = useQueryClient();
  const { data: services, isLoading: servicesLoading } = useQuery({ queryKey: ["services"], queryFn: () => api.getServices() });
  const { data: requests, isLoading: requestsLoading } = useQuery({ queryKey: ["serviceRequests"], queryFn: api.getServiceRequests });
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ServiceItem | null>(null);

  const createMut = useMutation({
    mutationFn: (payload: { name: string; description?: string; category?: string; pricing?: string; sla_hours?: number; approval_required?: boolean }) =>
      api.createService(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<ServiceItem> }) => api.updateService(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteService(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["services"] }),
  });

  const activeServices = (services || []).filter((s) => s.is_active);
  const categories = Array.from(new Set(activeServices.map((s) => s.category).filter(Boolean))) as string[];
  const filtered = activeServices.filter((s) => {
    const matchCat = !category || s.category === category;
    const matchSearch = !search || s.name.toLowerCase().includes(search.toLowerCase()) || (s.description || "").toLowerCase().includes(search.toLowerCase());
    return matchCat && matchSearch;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Service Catalog</h1>
          <p className="text-[13px] text-ink-500">
            {activeServices.length} active services · {requests?.length || 0} requests
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search services…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input-base input-search text-xs w-48"
            />
          </div>
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="input-base text-xs w-40">
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <button onClick={() => setShowForm(true)} className="btn-primary text-xs">
            <Plus className="w-4 h-4" strokeWidth={1.5} />
            Add Service
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="card-surface p-4">
          <p className="kpi-label">Active Services</p>
          <p className="kpi-value">{activeServices.length}</p>
        </div>
        <div className="card-surface p-4">
          <p className="kpi-label">Categories</p>
          <p className="kpi-value">{categories.length}</p>
        </div>
        <div className="card-surface p-4">
          <p className="kpi-label">Total Requests</p>
          <p className="kpi-value">{requests?.length || 0}</p>
        </div>
        <div className="card-surface p-4">
          <p className="kpi-label">Pending Fulfillment</p>
          <p className="kpi-value">{(requests || []).filter((r) => !r.fulfilled_at).length}</p>
        </div>
      </div>

      {/* Services table */}
      {servicesLoading ? (
        <div className="card-surface p-6 space-y-3">{[1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-12 w-full" />)}</div>
      ) : (
        <div className="card-surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-300 bg-linen-100">
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Service</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Category</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Pricing</th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">SLA</th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">Approval</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-400 text-sm">No services found.</td>
                </tr>
              ) : (
                filtered.map((s) => (
                  <tr key={s.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-moss-400/15 text-moss-500 flex items-center justify-center shrink-0">
                          <Package className="w-4 h-4" strokeWidth={1.5} />
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-ink-700">{s.name}</p>
                          {s.description && <p className="text-xs text-ink-400 truncate max-w-48">{s.description}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {s.category ? (
                        <span className="badge">{s.category}</span>
                      ) : (
                        <span className="text-ink-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-ink-600">{s.pricing || "—"}</td>
                    <td className="px-4 py-3 text-center tabular-nums text-ink-600">{s.sla_hours ? `${s.sla_hours}h` : "—"}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                        s.approval_required
                          ? "bg-amber-400/15 text-amber-600 border-amber-400/30"
                          : "bg-moss-400/15 text-moss-600 border-moss-400/30"
                      )}>
                        {s.approval_required ? "Required" : "Auto"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex items-center gap-1">
                        <button onClick={() => setEditing(s)} className="p-1.5 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200" title="Edit">
                          <Edit3 className="w-3.5 h-3.5" />
                        </button>
                        <button onClick={() => deleteMut.mutate(s.id)} className="p-1.5 rounded text-ink-400 hover:text-rust-500 hover:bg-rust-400/10" title="Deactivate">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Service Requests section */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <ShoppingCart className="w-4 h-4 text-ink-500" strokeWidth={1.5} />
          <h2 className="font-serif text-lg text-ink-700">Service Requests</h2>
        </div>
        {requestsLoading ? (
          <div className="card-surface p-6 space-y-3">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-10 w-full" />)}</div>
        ) : (
          <div className="card-surface overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-linen-300 bg-linen-100">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Ticket</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Service</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">Qty</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Justification</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody>
                {(requests || []).length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-ink-400 text-sm">No service requests yet.</td>
                  </tr>
                ) : (
                  (requests || []).map((r) => (
                    <tr key={r.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100">
                      <td className="px-4 py-3 text-xs font-mono text-ink-600">{r.ticket_id}</td>
                      <td className="px-4 py-3 font-medium text-ink-700">{r.service_name || "—"}</td>
                      <td className="px-4 py-3 text-center tabular-nums text-ink-600">{r.quantity}</td>
                      <td className="px-4 py-3 text-xs text-ink-500 max-w-48 truncate">{r.justification || "—"}</td>
                      <td className="px-4 py-3 text-center">
                        <span className={cn(
                          "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border",
                          r.fulfilled_at
                            ? "bg-emerald-400/15 text-emerald-600 border-emerald-400/30"
                            : "bg-blue-400/15 text-blue-600 border-blue-400/30"
                        )}>
                          {r.fulfilled_at ? "Fulfilled" : "Pending"}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create / Edit modal */}
      {(showForm || editing) && (
        <ServiceFormModal
          service={editing}
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

function ServiceFormModal({ service, onClose, onSubmit, loading, error }: {
  service: ServiceItem | null;
  onClose: () => void;
  onSubmit: (payload: { name: string; description?: string; category?: string; pricing?: string; sla_hours?: number; approval_required?: boolean }) => void;
  loading: boolean;
  error: unknown;
}) {
  const [name, setName] = useState(service?.name || "");
  const [description, setDescription] = useState(service?.description || "");
  const [category, setCategory] = useState(service?.category || "");
  const [pricing, setPricing] = useState(service?.pricing || "");
  const [slaHours, setSlaHours] = useState(service?.sla_hours?.toString() || "");
  const [approvalRequired, setApprovalRequired] = useState(service?.approval_required || false);

  const errorMsg = error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm" onClick={onClose}>
      <div className="card-surface w-full max-w-md p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl text-ink-700">{service ? "Edit Service" : "Add Service"}</h2>
          <button onClick={onClose} className="p-1 rounded text-ink-400 hover:bg-linen-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className="input-base" placeholder="Laptop provisioning" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input-base min-h-[80px]"
              placeholder="Brief description of the service…"
              rows={3}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Category</span>
            <input value={category} onChange={(e) => setCategory(e.target.value)} className="input-base" placeholder="Hardware" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Pricing</span>
            <input value={pricing} onChange={(e) => setPricing(e.target.value)} className="input-base" placeholder="$500 one-time" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">SLA (hours)</span>
            <input type="number" value={slaHours} onChange={(e) => setSlaHours(e.target.value)} className="input-base" placeholder="48" />
          </label>
          <label className="flex items-center justify-between py-1">
            <span className="text-xs font-medium text-ink-500">Requires Approval</span>
            <button
              type="button"
              onClick={() => setApprovalRequired(!approvalRequired)}
              className={cn(
                "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                approvalRequired ? "bg-amber-500" : "bg-linen-400"
              )}
            >
              <span className={cn(
                "inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform",
                approvalRequired ? "translate-x-[18px]" : "translate-x-[3px]"
              )} />
            </button>
          </label>
        </div>
        {errorMsg && <p className="text-xs text-rust-500">Failed: {errorMsg}</p>}
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200">Cancel</button>
          <button
            onClick={() => onSubmit({
              name,
              description: description || undefined,
              category: category || undefined,
              pricing: pricing || undefined,
              sla_hours: slaHours ? Number(slaHours) : undefined,
              approval_required: approvalRequired,
            })}
            disabled={loading || !name.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
            {service ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
