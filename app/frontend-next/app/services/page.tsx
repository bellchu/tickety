"use client";

import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Edit3, Package, Plus, Search, ShoppingCart, Trash2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { canManageOperationalRecords, isDemoContext } from "@/lib/auth";
import type { ServiceItem, ServiceRequest } from "@/lib/types";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Alert, EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { DataListCard, DataTable, DataTableViewport, ListText } from "@/components/ui";
import { PageFrame, PageHeader, SummaryStrip } from "@/components/layout/PageLayout";

type ServicePayload = {
  name: string;
  description?: string;
  category?: string | null;
  pricing?: string | null;
  sla_hours?: number | null;
  approval_required?: boolean;
};
type RequestAction = {
  request: ServiceRequest;
  kind: "approve" | "reject" | "fulfill" | "cancel";
};
const SERVICE_PAGE_SIZE = 50;
const SERVICE_REQUEST_PAGE_SIZE = 50;

export default function ServicesPage() {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [requestSearch, setRequestSearch] = useState("");
  const [debouncedRequestSearch, setDebouncedRequestSearch] = useState("");
  const [approvalFilter, setApprovalFilter] = useState("");
  const [fulfillmentFilter, setFulfillmentFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ServiceItem | null>(null);
  const [deleting, setDeleting] = useState<ServiceItem | null>(null);
  const [requestAction, setRequestAction] = useState<RequestAction | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"catalog" | "requests">("catalog");

  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManageCatalog = canManageOperationalRecords(authQuery.data);
  const canOperateRequests = canManageCatalog && isDemoContext(authQuery.data);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedRequestSearch(requestSearch.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [requestSearch]);
  const servicesQuery = useInfiniteQuery({
    queryKey: ["services", "catalog", category, debouncedSearch],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getServicesPage({
      category: category || undefined,
      search: debouncedSearch || undefined,
      isActive: true,
      limit: SERVICE_PAGE_SIZE,
      offset: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.hasMore
      ? lastPage.offset + lastPage.limit
      : undefined,
  });
  const requestsQuery = useInfiniteQuery({
    queryKey: ["serviceRequests", debouncedRequestSearch, approvalFilter, fulfillmentFilter],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getServiceRequestsPage({
      search: debouncedRequestSearch || undefined,
      approvalStatus: approvalFilter || undefined,
      fulfillmentStatus: fulfillmentFilter || undefined,
      limit: SERVICE_REQUEST_PAGE_SIZE,
      offset: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.hasMore
      ? lastPage.offset + lastPage.limit
      : undefined,
  });

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

  const activeServices = useMemo(
    () => servicesQuery.data?.pages.flatMap((page) => page.services) ?? [],
    [servicesQuery.data],
  );
  const requests = useMemo(
    () => requestsQuery.data?.pages.flatMap((page) => page.requests) ?? [],
    [requestsQuery.data],
  );
  const serviceSummary = servicesQuery.data?.pages[0]?.summary;
  const requestSummary = requestsQuery.data?.pages[0]?.summary;
  const categories = serviceSummary?.categoryOptions ?? [];
  const activeServiceCount = serviceSummary?.active ?? activeServices.length;
  const categoryCount = serviceSummary?.categoryCount ?? categories.length;
  const requestTotal = requestSummary?.total ?? requests.length;
  const pendingFulfillment = requestSummary?.awaitingFulfillment ?? 0;
  const actionError = approvalMut.error || fulfillmentMut.error || deleteMut.error;

  return <PageFrame width="wide">
    <PageHeader eyebrow="Request operations" icon={<Package className="h-4 w-4" />} title="Service catalog" description="Define dependable request paths, approval policy, fulfillment targets, and customer expectations." actions={canManageCatalog ? <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { setNotice(null); setShowForm(true); }}>Add service</Button> : undefined} />

    {notice && <Alert variant="success" title="Catalog updated">{notice}</Alert>}
    {actionError && <Alert variant="danger" title="Action could not be completed">{actionError instanceof Error ? actionError.message : "Please retry the request."}</Alert>}
    {authQuery.isError && <Alert variant="warning" title="Management access could not be verified">Catalog and request data remain visible, but write controls are hidden until the session check succeeds.</Alert>}

    <SummaryStrip label="Service catalog summary" className="grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
      <Metric label="Active services" value={activeServiceCount} featured />
      <Metric label="Categories" value={categoryCount} />
      <Metric label="Awaiting fulfillment" value={pendingFulfillment} attention={pendingFulfillment > 0} />
    </SummaryStrip>

    <div className="inline-flex w-full rounded-xl border border-linen-400 bg-linen-50 p-1 sm:w-auto" role="tablist" aria-label="Service workspace view">
      <button id="service-tab-catalog" type="button" role="tab" aria-selected={activeView === "catalog"} aria-controls="service-panel-catalog" onClick={() => setActiveView("catalog")} className={`min-h-11 flex-1 rounded-lg px-4 text-sm font-semibold transition-colors sm:min-h-10 sm:flex-none ${activeView === "catalog" ? "bg-[var(--color-primary-soft)] text-semantic-primary" : "text-ink-500 hover:bg-linen-200"}`}>Catalog <span className="ml-1 text-xs opacity-70">{activeServiceCount}</span></button>
      <button id="service-tab-requests" type="button" role="tab" aria-selected={activeView === "requests"} aria-controls="service-panel-requests" onClick={() => setActiveView("requests")} className={`min-h-11 flex-1 rounded-lg px-4 text-sm font-semibold transition-colors sm:min-h-10 sm:flex-none ${activeView === "requests" ? "bg-[var(--color-primary-soft)] text-semantic-primary" : "text-ink-500 hover:bg-linen-200"}`}>Requests <span className="ml-1 text-xs opacity-70">{requestTotal}</span></button>
    </div>

    {activeView === "catalog" && <section id="service-panel-catalog" role="tabpanel" aria-labelledby="service-tab-catalog catalog-heading" className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end"><div className="min-w-0 flex-1"><h2 id="catalog-heading" className="text-lg font-semibold text-ink-700">Catalog offering</h2><p className="mt-1 text-xs text-ink-400" aria-live="polite">{servicesQuery.isLoading ? "Loading services…" : `${activeServices.length} matching service${activeServices.length === 1 ? "" : "s"} loaded${servicesQuery.hasNextPage ? "; more available" : ""}`}</p></div><label className="relative block lg:w-80"><span className="sr-only">Search services</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" /><input type="search" maxLength={200} className="input-base input-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search services…" /></label><label className="lg:w-52"><span className="sr-only">Filter by category</span><select className="input-base" value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>{categories.map((value) => <option key={value}>{value}</option>)}</select></label></div>
      {serviceSummary?.categoryOptionsTruncated && <Alert variant="info" title="Category choices are abbreviated">Search still covers the complete active catalog, including categories not shown in this filter.</Alert>}
      {servicesQuery.isLoading ? <RouteSkeleton rows={4} /> : servicesQuery.isError && !activeServices.length ? <ErrorState title="Could not load the service catalog" description="Catalog data is temporarily unavailable." onRetry={() => servicesQuery.refetch()} retrying={servicesQuery.isFetching} /> : activeServices.length === 0 ? <EmptyState icon={<Package className="h-5 w-5" />} title={search || category ? "No services match these filters" : "No active services"} description={search || category ? "Clear the current filters to see more services." : canManageCatalog ? "Publish the first service to give requesters a consistent path." : "No active catalog offerings are available."} action={search || category ? <Button variant="secondary" onClick={() => { setSearch(""); setDebouncedSearch(""); setCategory(""); }}>Clear filters</Button> : canManageCatalog ? <Button onClick={() => setShowForm(true)} leadingIcon={<Plus className="h-4 w-4" />}>Add service</Button> : undefined} /> : <><ServiceResults services={activeServices} canManage={canManageCatalog} onEdit={setEditing} onDelete={setDeleting} />{servicesQuery.isFetchNextPageError && <Alert variant="danger" title="More services could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void servicesQuery.fetchNextPage()}>Retry</Button>}>The catalog entries already shown remain available.</Alert>}{servicesQuery.hasNextPage && !servicesQuery.isFetchNextPageError && <div className="flex justify-center"><Button variant="secondary" onClick={() => void servicesQuery.fetchNextPage()} pending={servicesQuery.isFetchingNextPage} pendingLabel="Loading more…">Load more services</Button></div>}</>}
    </section>}

    {activeView === "requests" && <section id="service-panel-requests" role="tabpanel" aria-labelledby="service-tab-requests requests-heading" className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end"><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><ShoppingCart className="h-4 w-4 text-ink-500" aria-hidden="true" /><h2 id="requests-heading" className="text-lg font-semibold text-ink-700">Request operations</h2></div><p className="mt-1 text-xs text-ink-400">{requestsQuery.isLoading ? "Loading service requests…" : `${requests.length} matching request${requests.length === 1 ? "" : "s"} loaded${requestsQuery.hasNextPage ? "; more available" : ""}`}</p></div><label className="relative block lg:w-72"><span className="sr-only">Search service requests</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" /><input type="search" maxLength={200} className="input-base input-search" value={requestSearch} onChange={(event) => setRequestSearch(event.target.value)} placeholder="Search ticket or service…" /></label><div className="grid grid-cols-2 gap-2 lg:w-[22rem]"><label><span className="sr-only">Filter approval state</span><select className="input-base" value={approvalFilter} onChange={(event) => setApprovalFilter(event.target.value)}><option value="">All approvals</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="not_required">Not required</option></select></label><label><span className="sr-only">Filter fulfillment state</span><select className="input-base" value={fulfillmentFilter} onChange={(event) => setFulfillmentFilter(event.target.value)}><option value="">All fulfillment</option><option value="pending">Pending</option><option value="fulfilled">Fulfilled</option><option value="cancelled">Cancelled</option></select></label></div></div>
      {!authQuery.isLoading && !canOperateRequests && <Alert variant="info" title="Request workflow is read only">Approval and fulfillment changes are available only to an authenticated demo administrator. Production request state is owned by the connected ticketing system.</Alert>}
      {requestsQuery.isLoading ? <RouteSkeleton rows={3} /> : requestsQuery.isError && !requests.length ? <ErrorState title="Could not load service requests" description="No decisions can be made until current request state is available." onRetry={() => requestsQuery.refetch()} retrying={requestsQuery.isFetching} /> : requests.length === 0 ? <EmptyState icon={<ShoppingCart className="h-5 w-5" />} title={requestSearch || approvalFilter || fulfillmentFilter ? "No requests match these filters" : "No service requests yet"} description={requestSearch || approvalFilter || fulfillmentFilter ? "Clear the filters to return to the complete request queue." : "Requests will appear here after they are submitted from a ticket workflow."} action={requestSearch || approvalFilter || fulfillmentFilter ? <Button variant="secondary" onClick={() => { setRequestSearch(""); setDebouncedRequestSearch(""); setApprovalFilter(""); setFulfillmentFilter(""); }}>Clear filters</Button> : undefined} /> : <><RequestResults requests={requests} canManage={canOperateRequests} pending={approvalMut.isPending || fulfillmentMut.isPending} onAction={(request, kind) => setRequestAction({ request, kind })} />{requestsQuery.isFetchNextPageError && <Alert variant="danger" title="More requests could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void requestsQuery.fetchNextPage()}>Retry</Button>}>The requests already shown remain available.</Alert>}{requestsQuery.hasNextPage && !requestsQuery.isFetchNextPageError && <div className="flex justify-center"><Button variant="secondary" onClick={() => void requestsQuery.fetchNextPage()} pending={requestsQuery.isFetchingNextPage} pendingLabel="Loading more…">Load more requests</Button></div>}</>}
    </section>}

    {canManageCatalog && <ServiceFormDialog open={showForm || Boolean(editing)} service={editing} onClose={() => { if (!createMut.isPending && !updateMut.isPending) { setShowForm(false); setEditing(null); createMut.reset(); updateMut.reset(); } }} onSubmit={(payload) => editing ? updateMut.mutate({ id: editing.id, payload }) : createMut.mutate(payload)} pending={createMut.isPending || updateMut.isPending} error={createMut.error || updateMut.error} />}
    {canManageCatalog && <ConfirmDialog open={Boolean(deleting)} onOpenChange={(open) => { if (!open) { setDeleting(null); deleteMut.reset(); } }} title="Deactivate service?" description={<>This removes <strong>{deleting?.name}</strong> from the active catalog. Existing request history remains available.</>} confirmLabel="Deactivate service" destructive pending={deleteMut.isPending} onConfirm={() => { if (deleting) deleteMut.mutate(deleting.id); }} />}
    {canOperateRequests && <ConfirmDialog
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
    />}
  </PageFrame>;
}

function Metric({ label, value, featured, attention }: { label: string; value: number; featured?: boolean; attention?: boolean }) { return <div className={`rounded-2xl border p-4 ${attention ? "border-amber-400/40 bg-[var(--color-warning-soft)]" : featured ? "border-clay-200 bg-[var(--color-primary-soft)]" : "border-linen-300 bg-linen-50"}`}><p className="text-xs font-medium text-ink-500">{label}</p><p className="mt-2 font-serif text-3xl tabular-nums text-ink-700">{value}</p></div>; }
function RouteSkeleton({ rows }: { rows: number }) { return <div className="card-surface space-y-3 p-4" aria-label="Loading content">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>; }

function ServiceResults({ services, canManage, onEdit, onDelete }: { services: ServiceItem[]; canManage: boolean; onEdit: (service: ServiceItem) => void; onDelete: (service: ServiceItem) => void }) {
  return <><div className="grid gap-3 md:hidden">{services.map((service) => <DataListCard key={service.id}><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0 flex-1"><ListText text={service.name} lines={2} className="font-semibold leading-5 text-ink-700" /><ListText text={service.description || "No description provided."} lines={3} className="mt-1 text-xs leading-5 text-ink-500" /></div><Badge className="shrink-0" variant={service.approval_required ? "warning" : "success"}>{service.approval_required ? "Approval" : "Automatic"}</Badge></div><dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-xs"><div className="min-w-0"><dt className="text-ink-400">Category</dt><dd className="mt-1"><ListText text={service.category || "Uncategorized"} lines={2} className="text-ink-600" /></dd></div><div><dt className="text-ink-400">Target</dt><dd className="mt-1 text-ink-600">{service.sla_hours ? `${service.sla_hours} hours` : "Not set"}</dd></div><div className="min-w-0"><dt className="text-ink-400">Pricing</dt><dd className="mt-1"><ListText text={service.pricing || "No charge shown"} lines={2} className="text-ink-600" /></dd></div>{canManage && <div className="flex items-end justify-end gap-1"><IconButton size="sm" aria-label={`Edit ${service.name}`} icon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(service)} /><IconButton size="sm" aria-label={`Deactivate ${service.name}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(service)} /></div>}</dl></DataListCard>)}</div><DataTableViewport label="Service catalog" className="card-surface hidden md:block"><DataTable className="min-w-[700px]"><colgroup><col className="w-[40%]" /><col className="w-[20%]" /><col className="w-[18%]" /><col className="w-[12%]" />{canManage && <col className="w-[10%]" />}</colgroup><thead><tr className="border-b border-linen-300 bg-linen-100 text-[11px] uppercase tracking-[0.12em] text-ink-400"><th className="px-4 py-3 font-semibold">Service</th><th className="px-4 py-3 font-semibold">Category</th><th className="px-4 py-3 font-semibold">Delivery</th><th className="px-4 py-3 font-semibold">Pricing</th>{canManage && <th className="px-4 py-3 text-right font-semibold"><span className="sr-only">Actions</span></th>}</tr></thead><tbody>{services.map((service) => <tr key={service.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100"><td className="px-4 py-3"><ListText text={service.name} lines={2} className="font-semibold leading-5 text-ink-700" /><ListText text={service.description || "No description"} lines={2} className="mt-1 text-xs leading-5 text-ink-400" /></td><td className="px-4 py-3"><ListText text={service.category || "Uncategorized"} lines={2} className="text-xs font-medium text-ink-600" /></td><td className="px-4 py-3"><Badge variant={service.approval_required ? "warning" : "success"}>{service.approval_required ? "Approval" : "Automatic"}</Badge><span className="mt-2 block text-xs tabular-nums text-ink-500">{service.sla_hours ? `${service.sla_hours}h target` : "No SLA target"}</span></td><td className="px-4 py-3"><ListText text={service.pricing || "—"} lines={2} className="text-xs text-ink-600" /></td>{canManage && <td className="px-4 py-3"><div className="flex justify-end gap-1"><IconButton size="sm" aria-label={`Edit ${service.name}`} icon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(service)} /><IconButton size="sm" aria-label={`Deactivate ${service.name}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(service)} /></div></td>}</tr>)}</tbody></DataTable></DataTableViewport></>;
}

function RequestStatus({ value }: { value: string }) { const variant: BadgeVariant = ["approved", "fulfilled", "not_required"].includes(value) ? "success" : ["rejected", "cancelled"].includes(value) ? "danger" : "warning"; return <Badge variant={variant} dot>{value.replaceAll("_", " ")}</Badge>; }

function RequestResults({ requests, canManage, pending, onAction }: { requests: ServiceRequest[]; canManage: boolean; pending: boolean; onAction: (request: ServiceRequest, kind: RequestAction["kind"]) => void }) {
  const controls = (request: ServiceRequest) => canManage ? <div className="flex justify-end gap-1">{request.approval_status === "pending" && <><IconButton size="sm" aria-label={`Approve ${request.service_name || "service request"}`} icon={<CheckCircle2 className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "approve")} /><IconButton size="sm" aria-label={`Reject ${request.service_name || "service request"}`} icon={<XCircle className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "reject")} /></>}{request.fulfillment_status === "pending" && !["pending", "rejected"].includes(request.approval_status) && <><IconButton size="sm" aria-label={`Mark ${request.service_name || "service request"} fulfilled`} icon={<CheckCircle2 className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "fulfill")} /><IconButton size="sm" aria-label={`Cancel fulfillment for ${request.service_name || "service request"}`} icon={<XCircle className="h-4 w-4" />} disabled={pending} onClick={() => onAction(request, "cancel")} /></>}</div> : null;
  return <><div className="grid gap-3 lg:hidden">{requests.map((request) => <DataListCard key={request.id}><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0 flex-1"><ListText text={request.service_name || "Unknown service"} lines={2} className="font-semibold leading-5 text-ink-700" /><ListText text={`Ticket ${request.ticket_id}`} lines="wrap" className="mt-1 font-mono text-[11px] text-ink-400" /></div><span className="shrink-0 text-xs tabular-nums text-ink-500">Qty {request.quantity}</span></div>{request.justification && <ListText text={request.justification} lines={3} className="mt-3 text-xs leading-5 text-ink-500" />}<div className="mt-4 flex flex-wrap items-center gap-2 border-t border-linen-300 pt-3"><RequestStatus value={request.approval_status} /><RequestStatus value={request.fulfillment_status} />{canManage && <div className="ml-auto">{controls(request)}</div>}</div></DataListCard>)}</div><DataTableViewport label="Service requests" className="card-surface hidden lg:block"><DataTable className="min-w-[760px]"><colgroup><col className="w-[34%]" /><col className="w-[28%]" /><col className="w-[14%]" /><col className="w-[14%]" />{canManage && <col className="w-[10%]" />}</colgroup><thead><tr className="border-b border-linen-300 bg-linen-100 text-[11px] uppercase tracking-[0.12em] text-ink-400"><th className="px-4 py-3 font-semibold">Ticket / service</th><th className="px-4 py-3 font-semibold">Request details</th><th className="px-4 py-3 font-semibold">Approval</th><th className="px-4 py-3 font-semibold">Fulfillment</th>{canManage && <th className="px-4 py-3 text-right font-semibold"><span className="sr-only">Actions</span></th>}</tr></thead><tbody>{requests.map((request) => <tr key={request.id} className="border-b border-linen-200 last:border-0 hover:bg-linen-100"><td className="px-4 py-3"><ListText text={request.service_name || "Unknown service"} lines={2} className="font-semibold leading-5 text-ink-700" /><ListText text={request.ticket_id} lines={1} className="mt-1 font-mono text-[11px] text-ink-400" /></td><td className="px-4 py-3"><ListText text={request.justification || "No justification provided"} lines={2} className="text-xs leading-5 text-ink-500" /><span className="mt-1 block text-[11px] tabular-nums text-ink-400">Quantity {request.quantity}</span></td><td className="px-4 py-3"><RequestStatus value={request.approval_status} /></td><td className="px-4 py-3"><RequestStatus value={request.fulfillment_status} /></td>{canManage && <td className="px-4 py-3">{controls(request)}</td>}</tr>)}</tbody></DataTable></DataTableViewport></>;
}

function ServiceFormDialog({ open, service, onClose, onSubmit, pending, error }: { open: boolean; service: ServiceItem | null; onClose: () => void; onSubmit: (payload: ServicePayload) => void; pending: boolean; error: unknown }) { const key = service?.id ?? (open ? "new" : "closed"); return <ServiceFormDialogBody key={key} {...{ open, service, onClose, onSubmit, pending, error }} />; }
function ServiceFormDialogBody({ open, service, onClose, onSubmit, pending, error }: { open: boolean; service: ServiceItem | null; onClose: () => void; onSubmit: (payload: ServicePayload) => void; pending: boolean; error: unknown }) {
  const [form, setForm] = useState({ name: service?.name || "", description: service?.description || "", category: service?.category || "", pricing: service?.pricing || "", sla_hours: service?.sla_hours?.toString() || "", approval_required: service?.approval_required || false });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((current) => ({ ...current, [key]: value }));
  const optionalValue = (value: string) => value.trim() || (service ? null : undefined);
  const errorMessage = error instanceof Error ? error.message : error ? "The service could not be saved." : null;
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title={service ? "Edit service" : "Add service"} description="Set clear requester expectations and an operational fulfillment policy." dismissible={!pending} footer={<><Button variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button><Button pending={pending} pendingLabel="Saving…" disabled={!form.name.trim()} onClick={() => onSubmit({ name: form.name.trim(), description: form.description.trim(), category: optionalValue(form.category), pricing: optionalValue(form.pricing), sla_hours: form.sla_hours ? Number(form.sla_hours) : service ? null : undefined, approval_required: form.approval_required })}>{service ? "Save changes" : "Publish service"}</Button></>}><div className="space-y-4">{errorMessage && <Alert variant="danger" title="Could not save service">{errorMessage}</Alert>}<Field label="Service name"><input className="input-base" maxLength={200} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Laptop provisioning" /></Field><Field label="Description"><textarea className="input-base min-h-24 resize-y" maxLength={20_000} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Describe what the requester receives…" /></Field><div className="grid gap-4 sm:grid-cols-2"><Field label="Category"><input className="input-base" maxLength={200} value={form.category} onChange={(e) => set("category", e.target.value)} placeholder="Hardware" /></Field><Field label="Fulfillment target (hours)"><input className="input-base" type="number" min="1" max="8760" step="1" value={form.sla_hours} onChange={(e) => set("sla_hours", e.target.value)} placeholder="48" /></Field></div><Field label="Pricing or chargeback"><input className="input-base" maxLength={500} value={form.pricing} onChange={(e) => set("pricing", e.target.value)} placeholder="$500 one-time" /></Field><label className="flex items-start gap-3 rounded-xl border border-linen-300 bg-linen-100 p-4"><input type="checkbox" className="mt-0.5 h-4 w-4" checked={form.approval_required} onChange={(e) => set("approval_required", e.target.checked)} /><span><span className="block text-sm font-semibold text-ink-700">Require approval</span><span className="mt-1 block text-xs leading-5 text-ink-500">Requests remain blocked until an authorized operator records a decision.</span></span></label></div></Dialog>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1.5 block text-xs font-semibold text-ink-500">{label}</span>{children}</label>; }
