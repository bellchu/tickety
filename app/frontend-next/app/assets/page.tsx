"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Asset, UserOut } from "@/lib/types";
import {
  Laptop, Plus, RefreshCw, Trash2, X, Search,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ASSET_TYPES = [
  { value: "", label: "All Types" },
  { value: "Hardware", label: "Hardware" },
  { value: "Software", label: "Software" },
  { value: "License", label: "License" },
  { value: "Network", label: "Network" },
  { value: "Facility", label: "Facility" },
];

const ASSET_STATUSES = [
  { value: "", label: "All Statuses" },
  { value: "Active", label: "Active" },
  { value: "Inactive", label: "Inactive" },
  { value: "Retired", label: "Retired" },
  { value: "In Repair", label: "In Repair" },
  { value: "Lost/Stolen", label: "Lost/Stolen" },
];

const STATUS_COLORS: Record<string, string> = {
  Active: "bg-emerald-400/15 text-emerald-600 border-emerald-400/30",
  Inactive: "bg-ink-400/15 text-ink-500 border-ink-400/30",
  Retired: "bg-clay-400/15 text-clay-500 border-clay-400/30",
  "In Repair": "bg-amber-400/15 text-amber-600 border-amber-400/30",
  "Lost/Stolen": "bg-rust-400/15 text-rust-500 border-rust-400/30",
};

const TYPE_COLORS: Record<string, string> = {
  Hardware: "bg-blue-400/15 text-blue-600 border-blue-400/30",
  Software: "bg-violet-400/15 text-violet-600 border-violet-400/30",
  License: "bg-cyan-400/15 text-cyan-600 border-cyan-400/30",
  Network: "bg-moss-400/15 text-moss-600 border-moss-400/30",
  Facility: "bg-amber-400/15 text-amber-600 border-amber-400/30",
};

const TYPE_ICONS: Record<string, typeof Laptop> = {
  Hardware: Laptop,
  Software: Laptop,
  License: Laptop,
  Network: Laptop,
  Facility: Laptop,
};

export default function AssetsPage() {
  const queryClient = useQueryClient();

  const [assetType, setAssetType] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["assetStats"],
    queryFn: api.getAssetStats,
  });

  const { data: assets, isLoading: assetsLoading } = useQuery({
    queryKey: ["assets", assetType, status, search],
    queryFn: () => api.getAssets(assetType || undefined, status || undefined, search || undefined),
  });

  const { data: users } = useQuery({
    queryKey: ["users"],
    queryFn: api.getUsers,
  });

  const createMut = useMutation({
    mutationFn: (payload: Partial<Asset>) => api.createAsset(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["assetStats"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<Asset> }) =>
      api.updateAsset(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["assetStats"] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteAsset(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["assetStats"] });
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Assets</h1>
          <p className="text-[13px] text-ink-500">
            {stats?.total ?? "—"} total assets · configuration management
          </p>
        </div>
        <button onClick={() => setShowForm(true)} className="btn-primary text-xs">
          <Plus className="w-4 h-4" strokeWidth={1.5} />
          Add Asset
        </button>
      </div>

      {/* Summary bar */}
      {statsLoading ? (
        <div className="grid grid-cols-5 gap-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="card-surface p-4 space-y-1.5">
              <div className="skeleton h-3 w-16" />
              <div className="skeleton h-6 w-10" />
            </div>
          ))}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-5 gap-3">
          <div className="card-surface p-4 space-y-1.5">
            <p className="kpi-label">Total Assets</p>
            <p className="kpi-value">{stats.total}</p>
          </div>
          {Object.entries(stats.by_type || {}).map(([type, count]) => (
            <div key={type} className="card-surface p-4 space-y-1.5">
              <p className="kpi-label">{type}</p>
              <p className="kpi-value">{count}</p>
            </div>
          ))}
        </div>
      ) : null}

      {/* Filter bar */}
      <div className="flex items-center gap-3">
        <select
          value={assetType}
          onChange={(e) => setAssetType(e.target.value)}
          className="input-base text-xs w-36"
        >
          {ASSET_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="input-base text-xs w-36"
        >
          {ASSET_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search assets…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input-base input-search text-xs"
          />
        </div>
      </div>

      {/* Assets table */}
      {assetsLoading ? (
        <div className="card-surface p-6 space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton h-12 w-full" />
          ))}
        </div>
      ) : !assets || assets.length === 0 ? (
        <div className="card-surface p-12 text-center text-ink-400">
          <Laptop className="w-8 h-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No assets found</p>
        </div>
      ) : (
        <div className="card-surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-300 bg-linen-100">
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Name</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Type</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Asset Tag</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Owner</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Location</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Vendor</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100">
                  <td className="px-4 py-3 font-medium text-ink-700">{a.name}</td>
                  <td className="px-4 py-3">
                    <span className={cn("badge", TYPE_COLORS[a.asset_type] || "bg-ink-400/15 text-ink-500 border-ink-400/30")}>
                      {a.asset_type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-500 tabular-nums">{a.asset_tag || "—"}</td>
                  <td className="px-4 py-3">
                    <span className={cn("badge", STATUS_COLORS[a.status] || "bg-ink-400/15 text-ink-500 border-ink-400/30")}>
                      {a.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-500">{a.owner_name || "—"}</td>
                  <td className="px-4 py-3 text-ink-500">{a.location || "—"}</td>
                  <td className="px-4 py-3 text-ink-500">{a.vendor || "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        onClick={() => setEditing(a)}
                        className="p-1.5 rounded text-ink-400 hover:text-ink-700 hover:bg-linen-200"
                        title="Edit"
                      >
                        <Laptop className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => deleteMut.mutate(a.id)}
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

      {/* Create / Edit modal */}
      {(showForm || editing) && (
        <AssetFormModal
          asset={editing}
          users={users || []}
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

function AssetFormModal({
  asset,
  users,
  onClose,
  onSubmit,
  loading,
  error,
}: {
  asset: Asset | null;
  users: UserOut[];
  onClose: () => void;
  onSubmit: (payload: Partial<Asset>) => void;
  loading: boolean;
  error: unknown;
}) {
  const [name, setName] = useState(asset?.name || "");
  const [assetType, setAssetType] = useState(asset?.asset_type || "Hardware");
  const [assetTag, setAssetTag] = useState(asset?.asset_tag || "");
  const [status, setStatus] = useState(asset?.status || "Active");
  const [ownerId, setOwnerId] = useState(asset?.owner_id || "");
  const [location, setLocation] = useState(asset?.location || "");
  const [vendor, setVendor] = useState(asset?.vendor || "");
  const [model, setModel] = useState(asset?.model || "");
  const [purchaseDate, setPurchaseDate] = useState(asset?.purchase_date || "");
  const [warrantyExpiry, setWarrantyExpiry] = useState(asset?.warranty_expiry || "");
  const [cost, setCost] = useState(asset?.cost != null ? String(asset.cost) : "");
  const [notes, setNotes] = useState(asset?.notes || "");

  const errorMsg = error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="card-surface w-full max-w-lg p-6 space-y-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl text-ink-700">
            {asset ? "Edit Asset" : "Add Asset"}
          </h2>
          <button onClick={onClose} className="p-1 rounded text-ink-400 hover:bg-linen-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input-base"
              placeholder="Dell Latitude 5540"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Asset Type</span>
              <select value={assetType} onChange={(e) => setAssetType(e.target.value)} className="input-base">
                {ASSET_TYPES.filter((t) => t.value).map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Status</span>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className="input-base">
                {ASSET_STATUSES.filter((s) => s.value).map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Asset Tag</span>
              <input
                value={assetTag}
                onChange={(e) => setAssetTag(e.target.value)}
                className="input-base"
                placeholder="IT-0042"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Owner</span>
              <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)} className="input-base">
                <option value="">Unassigned</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{u.name}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Location</span>
              <input
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                className="input-base"
                placeholder="HQ - Floor 3"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Vendor</span>
              <input
                value={vendor}
                onChange={(e) => setVendor(e.target.value)}
                className="input-base"
                placeholder="Dell Technologies"
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Model</span>
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="input-base"
                placeholder="Latitude 5540"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Cost</span>
              <input
                type="number"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                className="input-base"
                placeholder="1299.00"
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Purchase Date</span>
              <input
                type="date"
                value={purchaseDate}
                onChange={(e) => setPurchaseDate(e.target.value)}
                className="input-base"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-ink-500">Warranty Expiry</span>
              <input
                type="date"
                value={warrantyExpiry}
                onChange={(e) => setWarrantyExpiry(e.target.value)}
                className="input-base"
              />
            </label>
          </div>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Notes</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input-base min-h-[80px] resize-y"
              placeholder="Any additional notes…"
            />
          </label>
        </div>
        {errorMsg && <p className="text-xs text-rust-500">Failed: {errorMsg}</p>}
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200">
            Cancel
          </button>
          <button
            onClick={() =>
              onSubmit({
                name,
                asset_type: assetType,
                asset_tag: assetTag || undefined,
                status,
                owner_id: ownerId || undefined,
                location: location || undefined,
                vendor: vendor || undefined,
                model: model || undefined,
                purchase_date: purchaseDate || undefined,
                warranty_expiry: warrantyExpiry || undefined,
                cost: cost ? parseFloat(cost) : undefined,
                notes: notes || undefined,
              })
            }
            disabled={loading || !name.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
            {asset ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
