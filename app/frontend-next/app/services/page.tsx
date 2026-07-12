"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Edit3, Package, Plus, Search, ShoppingCart, Trash2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { ServiceItem, ServiceRequest } from "@/lib/types";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Alert, EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";

type ServicePayload = { name: string; description?: string; category?: string; pricing?: string; sla_hours?: number; approval_required?: boolean };
type RequestAction = {
  request: ServiceRequest;
  kind: "approve" | "reject" | "fulfill" | "cancel";
};

export default function ServicesPage() {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ServiceItem | null>(null);
  const [deleting, setDeleting] = useState<ServiceItem | null>(null);
  const [requestAction, setRequestAction] = useState<RequestAction | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const servicesQuery = useQuery({ queryKey: ["services"], queryFn: () => api.getServices() });
  const requestsQuery = useQuery({ queryKey: ["serviceRequests"], queryFn: api.getServiceRequests });

  const createMut = useMutation({
    mutationFn: (payload: ServicePayload) => api.createService(payload),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["services"] }); setShowForm(false); setNotice("Service published to the catalog."); },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<ServiceItem> }) => api.updateService(id, payload),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["services"] }); setEditing(null); setNotice("Service details updated."); },
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteService(id),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["services"] }); setDeleting(null); setNotice("Service deactivated."); },
  });
  const approvalMut = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "approved" | "rejected" }) => api.decideServiceRequestApproval(id, decision),
    onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["serviceRequests"] }), queryClient.invalidateQueries({ queryKey: ["tickets"] })]); setNotice("Approval decision recorded."); },
  });
  const fulfillmentMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "fulfilled" | "cancelled" }) => api.updateServiceRequestFulfillment(id, status),
    onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["serviceRequests"] }), queryClient.invalidateQueries({ queryKey: ["tickets"] })]); setNotice("Fulfillment state updated."); },
  });

  const activeServices = (servicesQuery.data ?? []).filter((service) => service.is_active);
  const categories = Array.from(new Set(activeServices.map((service) => service.category).filter((value): value is string => Boolean(value))));
  const filtered = activeServices.filter((service) => (!category || service.category === category) && (!search || `${service.name} ${service.description}`.toLowerCase().includes(search.toLowerCase())));
  const requests = requestsQuery.data ?? [];
  const pendingFulfillment = requests.filter((request) => request.fulfillment_status === "pending" && !["pending", "rejected"].includes(request.approval_status)).length;
  const actionError = approvalMut.error || fulfillmentMut.error || deleteMut.error;

  return <div className="space-y-8">
    <header className="flex flex-col gap-4 border-b border-linen-300 pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-ink-400"><Package className="h-4 w-4" aria-hidden="true" /> Request operations</div><h1 className="font-serif text-3xl tracking-tight text-ink-700 sm:text-4xl">Service catalog</h1><p className="mt-2 max-w-2xl text-sm text-ink-500">Define dependable request paths, approval policy, fulfillment targets, and customer expectations.</p></div>
      <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { setNotice(null); setShowForm(true); }}>Add service</Button>
    </header>

    {notice && <Alert variant="success" title="Catalog updated">{notice}</Alert>}
    {actionError && <Alert variant="danger" title="Action could not be completed">{actionError instanceof Error ? actionError.message : "Please retry the request."}</Alert>}

    <section aria-label="Service catalog summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Metric label="Active services" value={activeServices.length} featured />
      <Metric label="Categories" value={categories.length} />
      <Metric label="Total requests" value={requests.length} />
      <Metric label="Awaiting fulfillment" value={pendingFulfillment} attention={pendingFulfillment > 0} />
    </section>

    <section aria-labelledby="catalog-heading" className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end"><div className="min-w-0 flex-1"><h2 id="catalog-heading" className="text-lg font-semibold text-ink-700">Catalog offering</h2><p className="mt-1 text-xs text-ink-400" aria-live="polite">{servicesQuery.isLoading ? "Loading services…" : `${filtered.length} visible service${filtered.length === 1 ? "" : "s"}`}</p></div><label className="relative block lg:w-80"><span className="sr-only">Search services</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" /><input type="search" className="input-base input-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search services…" /></label><label className="lg:w-52"><span className="sr-only">Filter by category</span><select className="input-base" value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>{categories.map((value) => <option key={value}>{value}</option>)}</select></label></div>
      {servicesQuery.isLoading ? <RouteSkeleton rows={4} /> : servicesQuery.isError ? <ErrorState title="Could not load the service catalog" description="Catalog data is temporarily unavailable." onRetry={() => servicesQuery.refetch()} retrying={servicesQuery.isFetching} /> : filtered.length === 0 ? <EmptyState icon={<Package className="h-5 w-5" />} title={search || category ? "No services match these filters" : "No active services"} description={search || category ? "Clear the current filters to see more services." : "Publish the first service to give requesters a consistent path."} action={search || category ? <Button variant="secondary" onClick={() => { setSearch(""); setCategory(""); }}>Clear filters</Button> : <Button onClick={() => setShowForm(true)} leadingIcon={<Plus className="h-4 w-4" />}>Add service</Button>} /> : <ServiceResults services={filtered} onEdit={setEditing} onDelete={setDeleting} />}
    </section>

    <section aria-labelledby="requests-heading" className="space-y-4">
      <div><div className="flex items-center gap-2"><ShoppingCart className="h-4 w-4 text-ink-500" aria-hidden="true" /><h2 id="requests-heading" className="text-lg font-semibold text-ink-700">Request operations</h2></div><p className="mt-1 text-xs text-ink-400">Review approvals and move eligible requests through fulfillment.</p></div>
      {requestsQuery.isLoading ? <RouteSkeleton rows={3} /> : requestsQuery.isError ? <ErrorState title="Could not load service requests" description="No decisions can be made until current request state is available." onRetry={() => requestsQuery.refetch()} retrying={requestsQuery.isFetching} /> : requests.length === 0 ? <EmptyState icon={<ShoppingCart className="h-5 w-5" />} title="No service requests yet" description="Requests will appear here after they are submitted from a ticket workflow." /> : <RequestResults requests={requests} pending={approvalMut.isPending || fulfillmentMut.isPending} onAction={(request, kind) => setRequestAction({ request, kind })} />}
    </section>

    <ServiceFormDialog open={showForm || Boolean(editing)} service={editing} onClose={() => { if (!createMut.isPending && !updateMut.isPending) { setShowForm(false); setEditing(null); createMut.reset(); updateMut.reset(); } }} onSubmit={(payload) => editing ? updateMut.mutate({ id: editing.id, payload }) : createMut.mutate(payload)} pending={createMut.isPending || updateMut.isPending} error={createMut.error || updateMut.error} />
    <ConfirmDialog open={Boolean(deleting)} onOpenChange={(open) => { if (!open) { setDeleting(null); deleteMut.reset(); } }} title="Deactivate service?" description={<>This removes <strong>{deleting?.name}</strong> from the active catalog. Existing request history remains available.</>} confirmLabel="Deactivate service" destructive pending={deleteMut.isPending} onConfirm={() => { if (deleting) deleteMut.mutate(deleting.id); }} />
    <ConfirmDialog
      open={Boolean(requestAction)}
      onOpenChange={(open) => { if (!open && !approvalMut.isPending && !fulfillmentMut.isPending) setRequestAction(null); }}
      title={requestAction ? `${requestAction.kind === "approve" ? "Approve" : requestAction.kind === "reject" ? "Reject" : requestAction.kind === "fulfill" ? "Complete" : "Cancel"} this request?` : "Confirm request action"}
      description={<>This records <strong>{requestAction?.kind}</strong> for <strong>{requestAction?.request.service_name || "this service request"}</strong> and updates the linked workflow.</>}
      confirmLabel={requestAction?.kind === "approve" ? "Record approval" : requestAction?.kind === "reject" ? "Record rejection" : requestAction?.kind === "fulfill" ? "Mark fulfilled" : "Cancel fulfillment"}
      destructive={requestAction?.kind === "reject" || requestAction?.kind === "cancel"}
      pending={approvalMut.isPending || fulfillmentMut.isPending}
      onConfirm={() => {
        if (!requestAction) return;
        if (requestAction.kind === "approve" || requestAction.kind === "reject") {
          approvalMut.mutate({ id: requestAction.request.id, decision: requestAction.kind === "approve" ? "approved" : "rejected" }, { onSuccess: () => setRequestAction(null) });
        } else {
          fulfillmentMut.mutate({ id: requestAction.request.id, status: requestAction.kind === "fulfill" ? "fulfilled" : "cancelled" }, { onSuccess: () => setRequestAction(null) });
        }
      }}
    />
  </div>;
}

function Metric({ label, value, featured, attention }: { label: string; value: number; featured?: boolean; attention?: boolean }) { return <div className={`rounded-2xl border p-4 ${attention ? "border-amber-400/40 bg-[var(--color-warning-soft)]" : featured ? "border-clay-200 bg-[var(--color-primary-soft)]" : "border-linen-300 bg-linen-50"}`}><p className="text-xs font-medium text-ink-500">{label}</p><p className="mt-2 font-serif text-3xl tabular-nums text-ink-700">{value}</p></div>; }
function RouteSkeleton({ rows }: { rows: number }) { return <div className="card-surface space-y-3 p-4" aria-label="Loading content">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>; }

function ServiceResults({ services, onEdit, onDelete }: { services: ServiceItem[]; onEdit: (service: ServiceItem) => void; onDelete: (service: ServiceItem) => void }) {
  return <><div className="grid gap-3 md:hidden">{services.map((service) => <article key={service.id} className="card-surface p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-ink-700">{service.name}</p><p className="mt-1 text-xs leading-5 text-ink-500">{service.description || "No description provided."}</p></div><Badge variant={service.approval_required ? "warning" : "success"}>{service.approval_required ? "Approval" : "Automatic"}</Badge></div><dl className="mt-4 grid grid-cols-2 gap-3 text-xs"><div><dt className="text-ink-400">Category</dt><dd className="mt-1 text-ink-600">{service.category || "Uncategorized"}</dd></div><div><dt className="text-ink-400">Target</dt><dd className="mt-1 text-ink-600">{service.sla_hours ? `${service.sla_hours} hours` : "Not set"}</dd></div><div><dt className="text-ink-400">Pricing</dt><dd className="mt-1 text-ink-600">{service.pricing || "No charge shown"}</dd></div><div className="flex items-end justify-end gap-1"><IconButton size="sm" aria-label={`Edit ${service.name}`} icon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(service)} /><IconButton size="sm" aria-label={`Deactivate ${service.name}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(service)} /></div></dl></article>)}</div><div className="card-surface hidden overflow-x-auto md:block"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b border-linen-300 bg-linen-100 text-left text-[11px] uppercase tracking-[0.12em] text-ink-400"><th className="px-4 py-3 font-semibold">Service</th><th className="px-4 py-3 font-semibold">Category</th><th className="px-4 py-3 font-semibold">Pricing</th><th className="px-4 py-3 font-semibold">SLA</th><th className="px-4 py-3 font-semibold">Approval</th><th className="px-4 py-3 text-right font-semibold">Actions</th></tr></thead><tbody>{services.map((service) => <tr key={service.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100"><td className="max-w-sm px-4 py-3"><p className="font-semibold text-ink-700">{service.name}</p><p className="mt-0.5 truncate text-xs text-ink-400">{service.description || "No description"}</p></td><td className="px-4 py-3"><Badge>{service.category || "Uncategorized"}</Badge></td><td className="px-4 py-3 text-ink-600">{service.pricing || "—"}</td><td className="px-4 py-3 tabular-nums text-ink-600">{service.sla_hours ? `${service.sla_hours}h` : "—"}</td><td className="px-4 py-3"><Badge variant={service.approval_required ? "warning" : "success"}>{service.approval_required ? "Required" : "Automatic"}</Badge></td><td className="px-4 py-3"><div className="flex justify-end gap-1"><IconButton size="sm" aria-label={`Edit ${service.name}`} icon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(service)} /><IconButton size="sm" aria-label={`Deactivate ${service.name}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(service)} /></div></td></tr>)}</tbody></table></div></>;
}

function RequestStatus({ value }: { value: string }) { const variant: BadgeVariant = ["approved", "fulfilled", "not_required"].includes(value) ? "success" : ["rejected", "cancelled"].includes(value) ? "danger" : "warning"; return <Badge variant={variant} dot>{value.replaceAll("_", " ")}</Badge>; }

function RequestResults({ requests, pending, onAction }: { requests: ServiceRequest[]; pending: boolean; onAction: (request: ServiceRequest, kind: RequestAction["kind"]) => void }) {
  const controls = (request: ServiceRequest) => <div className="flex justify-end gap-1">{request.approval_status === "pending" && <><IconButton size="sm" aria-label={`Approve ${request.service_name || "service request"}`} icon={<CheckCircle2 className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "approve")} /><IconButton size="sm" aria-label={`Reject ${request.service_name || "service request"}`} icon={<XCircle className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "reject")} /></>}{request.fulfillment_status === "pending" && !["pending", "rejected"].includes(request.approval_status) && <><IconButton size="sm" aria-label={`Mark ${request.service_name || "service request"} fulfilled`} icon={<CheckCircle2 className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "fulfill")} /><IconButton size="sm" aria-label={`Cancel fulfillment for ${request.service_name || "service request"}`} icon={<XCircle className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "cancel")} /></>}</div>;
  return <><div className="grid gap-3 lg:hidden">{requests.map((request) => <article key={request.id} className="card-surface p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-ink-700">{request.service_name || "Unknown service"}</p><p className="mt-1 font-mono text-[11px] text-ink-400">Ticket {request.ticket_id}</p></div><span className="text-xs text-ink-500">Qty {request.quantity}</span></div>{request.justification && <p className="mt-3 text-xs leading-5 text-ink-500">{request.justification}</p>}<div className="mt-4 flex flex-wrap items-center gap-2"><RequestStatus value={request.approval_status} /><RequestStatus value={request.fulfillment_status} /><div className="ml-auto">{controls(request)}</div></div></article>)}</div><div className="card-surface hidden overflow-x-auto lg:block"><table className="w-full min-w-[900px] text-sm"><thead><tr className="border-b border-linen-300 bg-linen-100 text-left text-[11px] uppercase tracking-[0.12em] text-ink-400"><th className="px-4 py-3 font-semibold">Ticket / service</th><th className="px-4 py-3 font-semibold">Qty</th><th className="px-4 py-3 font-semibold">Justification</th><th className="px-4 py-3 font-semibold">Approval</th><th className="px-4 py-3 font-semibold">Fulfillment</th><th className="px-4 py-3 text-right font-semibold">Actions</th></tr></thead><tbody>{requests.map((request) => <tr key={request.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100"><td className="px-4 py-3"><p className="font-semibold text-ink-700">{request.service_name || "Unknown service"}</p><p className="mt-0.5 font-mono text-[11px] text-ink-400">{request.ticket_id}</p></td><td className="px-4 py-3 tabular-nums text-ink-600">{request.quantity}</td><td className="max-w-xs px-4 py-3"><p className="truncate text-xs text-ink-500">{request.justification || "—"}</p></td><td className="px-4 py-3"><RequestStatus value={request.approval_status} /></td><td className="px-4 py-3"><RequestStatus value={request.fulfillment_status} /></td><td className="px-4 py-3">{controls(request)}</td></tr>)}</tbody></table></div></>;
}

function ServiceFormDialog({ open, service, onClose, onSubmit, pending, error }: { open: boolean; service: ServiceItem | null; onClose: () => void; onSubmit: (payload: ServicePayload) => void; pending: boolean; error: unknown }) { const key = service?.id ?? (open ? "new" : "closed"); return <ServiceFormDialogBody key={key} {...{ open, service, onClose, onSubmit, pending, error }} />; }
function ServiceFormDialogBody({ open, service, onClose, onSubmit, pending, error }: { open: boolean; service: ServiceItem | null; onClose: () => void; onSubmit: (payload: ServicePayload) => void; pending: boolean; error: unknown }) {
  const [form, setForm] = useState({ name: service?.name || "", description: service?.description || "", category: service?.category || "", pricing: service?.pricing || "", sla_hours: service?.sla_hours?.toString() || "", approval_required: service?.approval_required || false });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((current) => ({ ...current, [key]: value }));
  const errorMessage = error instanceof Error ? error.message : error ? "The service could not be saved." : null;
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title={service ? "Edit service" : "Add service"} description="Set clear requester expectations and an operational fulfillment policy." dismissible={!pending} footer={<><Button variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button><Button pending={pending} pendingLabel="Saving…" disabled={!form.name.trim()} onClick={() => onSubmit({ name: form.name.trim(), description: form.description || undefined, category: form.category || undefined, pricing: form.pricing || undefined, sla_hours: form.sla_hours ? Number(form.sla_hours) : undefined, approval_required: form.approval_required })}>{service ? "Save changes" : "Publish service"}</Button></>}><div className="space-y-4">{errorMessage && <Alert variant="danger" title="Could not save service">{errorMessage}</Alert>}<Field label="Service name"><input className="input-base" value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Laptop provisioning" /></Field><Field label="Description"><textarea className="input-base min-h-24 resize-y" value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Describe what the requester receives…" /></Field><div className="grid gap-4 sm:grid-cols-2"><Field label="Category"><input className="input-base" value={form.category} onChange={(e) => set("category", e.target.value)} placeholder="Hardware" /></Field><Field label="Fulfillment target (hours)"><input className="input-base" type="number" min="1" value={form.sla_hours} onChange={(e) => set("sla_hours", e.target.value)} placeholder="48" /></Field></div><Field label="Pricing or chargeback"><input className="input-base" value={form.pricing} onChange={(e) => set("pricing", e.target.value)} placeholder="$500 one-time" /></Field><label className="flex items-start gap-3 rounded-xl border border-linen-300 bg-linen-100 p-4"><input type="checkbox" className="mt-0.5 h-4 w-4" checked={form.approval_required} onChange={(e) => set("approval_required", e.target.checked)} /><span><span className="block text-sm font-semibold text-ink-700">Require approval</span><span className="mt-1 block text-xs leading-5 text-ink-500">Requests remain blocked until an authorized operator records a decision.</span></span></label></div></Dialog>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1.5 block text-xs font-semibold text-ink-500">{label}</span>{children}</label>; }
