"use client";

import { useEffect, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit3, Laptop, Plus, Search, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { canManageOperationalRecords } from "@/lib/auth";
import type { Asset, UserOut } from "@/lib/types";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Alert, EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { DataListCard, DataTable, DataTableViewport, ListText } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";

const ASSET_TYPES = ["Hardware", "Software", "License", "Network", "Facility"];
const ASSET_STATUSES = ["In Use", "Available", "Retired", "Broken", "Lost"];
const ASSET_PAGE_SIZE = 50;

const statusVariant = (status: string): BadgeVariant => {
  if (status === "In Use" || status === "Available") return "success";
  if (status === "Broken") return "warning";
  if (status === "Lost") return "danger";
  return "neutral";
};

export default function AssetsPage() {
  const queryClient = useQueryClient();
  const [assetType, setAssetType] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [deleting, setDeleting] = useState<Asset | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManage = canManageOperationalRecords(authQuery.data);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  const assetsQuery = useInfiniteQuery({
    queryKey: ["assets", assetType, status, debouncedSearch],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getAssetsPage({
      assetType: assetType || undefined,
      status: status || undefined,
      search: debouncedSearch || undefined,
      limit: ASSET_PAGE_SIZE,
      offset: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.hasMore
      ? lastPage.offset + lastPage.limit
      : undefined,
  });
  const usersQuery = useQuery({ queryKey: ["users", "asset-options"], queryFn: () => api.getUsersPage({ isActive: true, limit: 200 }), enabled: canManage });

  const refreshAssets = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["assets"] }),
    ]);
  };

  const createMut = useMutation({
    mutationFn: (payload: Partial<Asset>) => api.createAsset(payload),
    onSuccess: async () => {
      await refreshAssets();
      setShowForm(false);
      setNotice("Asset added to the configuration inventory.");
    },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<Asset> }) => api.updateAsset(id, payload),
    onSuccess: async () => {
      await refreshAssets();
      setEditing(null);
      setNotice("Asset details updated.");
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteAsset(id),
    onSuccess: async () => {
      await refreshAssets();
      setDeleting(null);
      setNotice("Asset retired while preserving its ticket and audit history.");
    },
  });

  const assets = assetsQuery.data?.pages.flatMap((page) => page.assets) ?? [];
  const hasFilters = Boolean(assetType || status || search.trim());

  return (
    <PageFrame width="wide">
      <PageHeader eyebrow="Configuration management" icon={<ShieldCheck className="h-4 w-4" />} title="Assets" description="Track ownership, lifecycle, location, and warranty exposure across the estate." actions={canManage ? <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { setNotice(null); setShowForm(true); }}>Add asset</Button> : undefined} />

      {notice && <Alert variant="success" title="Inventory updated">{notice}</Alert>}
      {authQuery.isError && <Alert variant="warning" title="Management access could not be verified">The inventory remains visible, but write controls are hidden until the session check succeeds.</Alert>}
      {(deleteMut.isError || (canManage && usersQuery.isError)) && (
        <Alert variant="danger" title="Some asset actions are unavailable">
          {deleteMut.error instanceof Error ? deleteMut.error.message : "Could not load owners or complete the requested change. Try again."}
        </Alert>
      )}
      {canManage && usersQuery.data?.hasMore && <Alert variant="info" title="Owner directory is truncated">The first 200 active accounts are available for asset ownership. Search the Agents directory before assigning an account outside this list.</Alert>}

      <section aria-labelledby="asset-inventory-heading" className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <div className="min-w-0 flex-1">
            <h2 id="asset-inventory-heading" className="text-lg font-semibold text-ink-700">Inventory</h2>
            <p className="mt-1 text-xs text-ink-400" aria-live="polite">{assetsQuery.isLoading ? "Loading assets…" : `${assets.length} matching asset${assets.length === 1 ? "" : "s"} loaded${assetsQuery.hasNextPage ? "; more available" : ""}`}</p>
          </div>
          <label className="relative block min-w-0 flex-1 lg:max-w-sm">
            <span className="sr-only">Search assets</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
            <input className="input-base input-search" maxLength={200} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, tag, vendor…" type="search" />
          </label>
          <div className="grid grid-cols-2 gap-3 lg:w-[22rem]">
            <label><span className="sr-only">Filter by asset type</span><select className="input-base" value={assetType} onChange={(e) => setAssetType(e.target.value)}><option value="">All types</option>{ASSET_TYPES.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label><span className="sr-only">Filter by status</span><select className="input-base" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{ASSET_STATUSES.map((value) => <option key={value}>{value}</option>)}</select></label>
          </div>
        </div>

        {assetsQuery.isLoading ? <AssetSkeleton /> : assetsQuery.isError && !assets.length ? (
          <ErrorState title="Could not load assets" description="The inventory service did not return a usable response." onRetry={() => assetsQuery.refetch()} retrying={assetsQuery.isFetching} />
        ) : assets.length === 0 ? (
          <EmptyState
            icon={<Laptop className="h-5 w-5" />}
            title={hasFilters ? "No assets match these filters" : "No assets in the inventory"}
            description={hasFilters ? "Adjust or clear the filters to widen the result set." : canManage ? "Add the first asset to establish ownership and lifecycle visibility." : "No assets are available in this inventory."}
            action={hasFilters ? <Button variant="secondary" onClick={() => { setAssetType(""); setStatus(""); setSearch(""); setDebouncedSearch(""); }}>Clear filters</Button> : canManage ? <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => setShowForm(true)}>Add asset</Button> : undefined}
          />
        ) : <>
          <AssetResults assets={assets} canManage={canManage} onEdit={setEditing} onDelete={setDeleting} />
          {assetsQuery.isFetchNextPageError && <Alert variant="danger" title="More assets could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void assetsQuery.fetchNextPage()}>Retry</Button>}>The assets already shown remain available.</Alert>}
          {assetsQuery.hasNextPage && !assetsQuery.isFetchNextPageError && <div className="flex justify-center pt-2"><Button variant="secondary" onClick={() => void assetsQuery.fetchNextPage()} pending={assetsQuery.isFetchingNextPage} pendingLabel="Loading more…">Load more assets</Button></div>}
        </>}
      </section>

      {canManage && <AssetFormDialog
        open={showForm || Boolean(editing)} asset={editing} users={usersQuery.data?.users ?? []}
        onClose={() => { if (!createMut.isPending && !updateMut.isPending) { setShowForm(false); setEditing(null); createMut.reset(); updateMut.reset(); } }}
        onSubmit={(payload) => editing ? updateMut.mutate({ id: editing.id, payload }) : createMut.mutate(payload)}
        pending={createMut.isPending || updateMut.isPending} error={createMut.error || updateMut.error}
      />}
      {canManage && <ConfirmDialog
        open={Boolean(deleting)} onOpenChange={(open) => { if (!open) { setDeleting(null); deleteMut.reset(); } }}
        title="Retire asset?" description={<><strong>{deleting?.name}</strong> will leave active service while its ticket and audit history remain intact.</>}
        confirmLabel="Retire asset" destructive pending={deleteMut.isPending} onConfirm={() => { if (deleting) deleteMut.mutate(deleting.id); }}
      />}
    </PageFrame>
  );
}

function AssetSkeleton() { return <div className="card-surface space-y-3 p-4" aria-label="Loading asset inventory">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-14" />)}</div>; }

function AssetResults({ assets, canManage, onEdit, onDelete }: { assets: Asset[]; canManage: boolean; onEdit: (asset: Asset) => void; onDelete: (asset: Asset) => void }) {
  return <>
    <div className="grid gap-3 md:hidden">{assets.map((asset) => <DataListCard key={asset.id}><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0 flex-1"><ListText text={asset.name} lines={2} className="font-semibold leading-5 text-ink-700" /><ListText text={`${asset.asset_tag || "No asset tag"} · ${asset.asset_type}`} lines={2} className="mt-1 text-xs text-ink-400" /></div><Badge className="shrink-0" variant={statusVariant(asset.status)} dot>{asset.status}</Badge></div><dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-linen-300 pt-3 text-xs"><div className="min-w-0"><dt className="text-ink-400">Owner</dt><dd className="mt-1"><ListText text={asset.owner_name || "Unassigned"} lines={2} className="text-ink-600" /></dd></div><div className="min-w-0"><dt className="text-ink-400">Location</dt><dd className="mt-1"><ListText text={asset.location || "Not recorded"} lines={2} className="text-ink-600" /></dd></div><div className="min-w-0"><dt className="text-ink-400">Vendor / model</dt><dd className="mt-1"><ListText text={[asset.vendor, asset.model].filter(Boolean).join(" · ") || "Not recorded"} lines={3} className="text-ink-600" /></dd></div>{canManage && <div className="flex items-end justify-end gap-1"><IconButton size="sm" icon={<Edit3 className="h-4 w-4" />} aria-label={`Edit ${asset.name}`} onClick={() => onEdit(asset)} /><IconButton size="sm" icon={<Trash2 className="h-4 w-4" />} aria-label={`Remove ${asset.name}`} onClick={() => onDelete(asset)} /></div>}</dl></DataListCard>)}</div>
    <DataTableViewport label="Asset inventory" className="card-surface hidden md:block"><DataTable className="min-w-[720px]"><colgroup><col className="w-[28%]" /><col className="w-[18%]" /><col className="w-[24%]" /><col className="w-[20%]" />{canManage && <col className="w-[10%]" />}</colgroup><thead><tr className="border-b border-linen-300 bg-linen-100 text-[11px] uppercase tracking-[0.12em] text-ink-400"><th className="px-4 py-3 font-semibold">Asset</th><th className="px-4 py-3 font-semibold">Classification</th><th className="px-4 py-3 font-semibold">Assignment</th><th className="px-4 py-3 font-semibold">Make / model</th>{canManage && <th className="px-4 py-3 text-right font-semibold"><span className="sr-only">Actions</span></th>}</tr></thead><tbody>{assets.map((asset) => <tr key={asset.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100"><td className="px-4 py-3"><ListText text={asset.name} lines={2} className="font-semibold leading-5 text-ink-700" /><ListText text={asset.asset_tag || "No tag"} lines={1} className="mt-1 text-xs text-ink-400" /></td><td className="px-4 py-3"><ListText text={asset.asset_type} lines={2} className="text-xs font-medium text-ink-600" /><Badge className="mt-2" variant={statusVariant(asset.status)} dot>{asset.status}</Badge></td><td className="px-4 py-3"><ListText text={asset.owner_name || "Unassigned"} lines={2} className="text-xs font-medium text-ink-600" /><ListText text={asset.location || "Location not recorded"} lines={2} className="mt-1 text-[11px] text-ink-400" /></td><td className="px-4 py-3"><ListText text={[asset.vendor, asset.model].filter(Boolean).join(" · ") || "—"} lines={3} className="text-xs leading-5 text-ink-600" /></td>{canManage && <td className="px-4 py-3"><div className="flex justify-end gap-1"><IconButton size="sm" icon={<Edit3 className="h-4 w-4" />} aria-label={`Edit ${asset.name}`} onClick={() => onEdit(asset)} /><IconButton size="sm" icon={<Trash2 className="h-4 w-4" />} aria-label={`Remove ${asset.name}`} onClick={() => onDelete(asset)} /></div></td>}</tr>)}</tbody></DataTable></DataTableViewport>
  </>;
}

function AssetFormDialog({ open, asset, users, onClose, onSubmit, pending, error }: { open: boolean; asset: Asset | null; users: UserOut[]; onClose: () => void; onSubmit: (payload: Partial<Asset>) => void; pending: boolean; error: unknown }) {
  const key = asset?.id ?? (open ? "new" : "closed");
  return <AssetFormDialogBody key={key} {...{ open, asset, users, onClose, onSubmit, pending, error }} />;
}

function AssetFormDialogBody({ open, asset, users, onClose, onSubmit, pending, error }: { open: boolean; asset: Asset | null; users: UserOut[]; onClose: () => void; onSubmit: (payload: Partial<Asset>) => void; pending: boolean; error: unknown }) {
  const [form, setForm] = useState({ name: asset?.name || "", asset_type: asset?.asset_type || "Hardware", asset_tag: asset?.asset_tag || "", status: asset?.status || "In Use", owner_id: asset?.owner_id || "", location: asset?.location || "", vendor: asset?.vendor || "", model: asset?.model || "", purchase_date: asset?.purchase_date?.slice(0, 10) || "", warranty_expiry: asset?.warranty_expiry?.slice(0, 10) || "", cost: asset?.cost == null ? "" : String(asset.cost), notes: asset?.notes || "" });
  const set = (field: keyof typeof form, value: string) => setForm((current) => ({ ...current, [field]: value }));
  const optionalValue = (value: string) => value.trim() || (asset ? null : undefined);
  const field = (label: string, name: keyof typeof form, placeholder?: string, type = "text") => <label className="block"><span className="mb-1.5 block text-xs font-semibold text-ink-500">{label}</span><input className="input-base" type={type} value={form[name]} onChange={(e) => set(name, e.target.value)} placeholder={placeholder} /></label>;
  const errorMessage = error instanceof Error ? error.message : error ? "The asset could not be saved." : null;
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title={asset ? "Edit asset" : "Add asset"} description="Keep lifecycle and ownership information accurate for support and audit workflows." className="max-w-2xl" dismissible={!pending} footer={<><Button variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button><Button pending={pending} pendingLabel="Saving…" disabled={!form.name.trim()} onClick={() => onSubmit({ name: form.name.trim(), asset_type: form.asset_type, asset_tag: optionalValue(form.asset_tag), status: form.status, owner_id: optionalValue(form.owner_id), location: optionalValue(form.location), vendor: optionalValue(form.vendor), model: optionalValue(form.model), purchase_date: optionalValue(form.purchase_date), warranty_expiry: optionalValue(form.warranty_expiry), cost: form.cost ? Number(form.cost) : asset ? null : undefined, notes: optionalValue(form.notes) })}>{asset ? "Save changes" : "Add asset"}</Button></>}>
    <div className="space-y-4">{errorMessage && <Alert variant="danger" title="Could not save asset">{errorMessage}</Alert>}{field("Asset name", "name", "Dell Latitude 5540")}<div className="grid gap-4 sm:grid-cols-2"><label><span className="mb-1.5 block text-xs font-semibold text-ink-500">Asset type</span><select className="input-base" value={form.asset_type} onChange={(e) => set("asset_type", e.target.value)}>{ASSET_TYPES.map((value) => <option key={value}>{value}</option>)}</select></label><label><span className="mb-1.5 block text-xs font-semibold text-ink-500">Status</span><select className="input-base" value={form.status} onChange={(e) => set("status", e.target.value)}>{ASSET_STATUSES.map((value) => <option key={value}>{value}</option>)}</select></label>{field("Asset tag", "asset_tag", "IT-0042")}<label><span className="mb-1.5 block text-xs font-semibold text-ink-500">Owner</span><select className="input-base" value={form.owner_id} onChange={(e) => set("owner_id", e.target.value)}><option value="">Unassigned</option>{users.map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}</select></label>{field("Location", "location", "HQ · Floor 3")}{field("Vendor", "vendor", "Dell Technologies")}{field("Model", "model", "Latitude 5540")}{field("Cost", "cost", "1299.00", "number")}{field("Purchase date", "purchase_date", undefined, "date")}{field("Warranty expiry", "warranty_expiry", undefined, "date")}</div><label><span className="mb-1.5 block text-xs font-semibold text-ink-500">Notes</span><textarea className="input-base min-h-24 resize-y" value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Lifecycle, support, or compliance context…" /></label></div>
  </Dialog>;
}
