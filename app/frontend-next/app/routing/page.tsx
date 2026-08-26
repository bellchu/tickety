"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, ListChecks, Pencil, Plus, Search, ShieldCheck, Waypoints } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { PageFrame, PageHeader, SectionHeader, SummaryStrip } from "@/components/layout/PageLayout";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence, isDemoContext } from "@/lib/auth";
import { resolverGroupByCode, resolverGroupCatalog } from "@/lib/resolver-groups";
import type { AgentTeamMapping, ResolverGroup, RoutingRule, RoutingRuleDraft } from "@/lib/types";

const emptyRule: RoutingRuleDraft = {
  name: "",
  description: null,
  enabled: true,
  priority: 100,
  business_context: null,
  scope: null,
  service_contains: null,
  failure_domain_contains: null,
  primary_group: "INFRA_HELPDESK",
  secondary_group: null,
};

function RoutingHeader() {
  return <PageHeader
    eyebrow="Routing control plane"
    icon={<Waypoints className="h-4 w-4" />}
    title="Routing & triage"
    description="Manage auto-triage, structured routing guidance, and local agent-to-team memberships without changing Tickety's protected AI contract or writing to the provider catalog."
    meta="Resolver recommendations remain advisory; catalog mapping is pending."
  />;
}

export default function RoutingPage() {
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const allowed = canAccessProtectedIntelligence(authQuery.data);
  if (authQuery.isLoading) return <PageFrame width="wide"><RoutingHeader /><Skeleton className="h-80 w-full" /></PageFrame>;
  if (authQuery.isError) return <PageFrame width="wide"><RoutingHeader /><ErrorState title="Routing access could not be checked" description="No management data was requested because your session could not be verified." onRetry={() => void authQuery.refetch()} /></PageFrame>;
  if (!allowed) return <PageFrame width="wide"><RoutingHeader /><EmptyState icon={<ShieldCheck className="h-5 w-5" />} title={isDemoContext(authQuery.data) ? "Demo administrator access required" : "Administrator or supervisor access required"} description="This workspace is restricted to authenticated routing administrators and supervisors." /></PageFrame>;
  return <RoutingWorkspace />;
}

function RoutingWorkspace() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [editingAgent, setEditingAgent] = useState<AgentTeamMapping | null>(null);
  const [editingRule, setEditingRule] = useState<RoutingRule | null | "new">(null);
  const [triageConfirm, setTriageConfirm] = useState(false);
  const [windowUnit, setWindowUnit] = useState<"days" | "weeks">("days");
  const [windowValue, setWindowValue] = useState(7);

  const statusQuery = useQuery({ queryKey: ["routing", "status"], queryFn: api.getRoutingTriageStatus });
  const mappingsQuery = useQuery({
    queryKey: ["routing", "agent-team-mappings", search, offset],
    queryFn: () => api.getAgentTeamMappings({ search, active: true, limit: 50, offset }),
  });
  const rulesQuery = useQuery({ queryKey: ["routing", "rules"], queryFn: api.getRoutingRules });
  const catalogQuery = useQuery({ queryKey: ["routing", "catalog-recommendations"], queryFn: api.getRoutingCatalogRecommendations });

  const triageMutation = useMutation({
    mutationFn: () => api.triageAllUntriaged(windowUnit, windowValue),
    onSuccess: () => setTriageConfirm(false),
  });
  const automationMutation = useMutation({
    mutationFn: api.updateRoutingTriageAutomation,
    onSuccess: (data) => queryClient.setQueryData(["routing", "status"], data),
  });

  const status = statusQuery.data;
  const mappings = mappingsQuery.data;
  const mappedAgents = mappings?.items.filter((item) => item.resolver_groups.length > 0).length ?? 0;
  const triageWindowValid = Number.isInteger(windowValue)
    && windowValue >= 1
    && windowValue <= (windowUnit === "days" ? 7 : 4);

  return <PageFrame width="wide">
    <RoutingHeader />
    <SummaryStrip label="Routing and triage status">
      <StatusCard label="Auto-triage" value={status?.auto_triage.effective ? "Running" : "Paused"} detail="AI classification for incoming tickets" />
      <StatusCard label="Auto-routing" value={status?.auto_routing.effective ? "Advisory on" : "Advisory off"} detail="Never assigns a provider group automatically" />
      <StatusCard label="Local team mappings" value={`${mappedAgents}/${mappings?.items.length ?? 0}`} detail="Agents mapped on this page" />
      <StatusCard label="Catalog mapping" value="Pending" detail={`${catalogQuery.data?.recommendations.length ?? 0} recommendation(s) ready`} />
    </SummaryStrip>

    {(statusQuery.isError || mappingsQuery.isError || rulesQuery.isError) && <Alert variant="danger" title="Some routing controls are unavailable">Refresh the page before making changes.</Alert>}

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]">
      <SectionHeader title="Automation & triage queue" description="Auto-triage remains part of the existing AI worker. Administrators can change automation state; supervisors can run the bounded triage queue." />
      {statusQuery.isLoading ? <Skeleton className="mt-5 h-24 w-full" /> : status && <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-linen-400 bg-linen-100 p-4">
          <div className="flex items-start justify-between gap-4"><div><h3 className="text-sm font-semibold text-ink-700">Ambient AI</h3><p className="mt-1 text-xs leading-5 text-ink-500">Triage classifies tickets; routing adds a resolver recommendation.</p></div><Bot className="h-5 w-5 text-semantic-primary" /></div>
          <div className="mt-4 space-y-3">
            <label className="flex items-center justify-between gap-4 text-sm text-ink-600"><span>Auto-triage</span><input aria-label="Auto-triage" type="checkbox" checked={status.auto_triage.configured} disabled={!status.automation_controls_editable || automationMutation.isPending} onChange={(event) => automationMutation.mutate({ auto_triage_enabled: event.target.checked, auto_routing_enabled: status.auto_routing.configured })} /></label>
            <label className="flex items-center justify-between gap-4 text-sm text-ink-600"><span>Advisory auto-routing</span><input aria-label="Advisory auto-routing" type="checkbox" checked={status.auto_routing.configured} disabled={!status.automation_controls_editable || automationMutation.isPending} onChange={(event) => automationMutation.mutate({ auto_triage_enabled: status.auto_triage.configured, auto_routing_enabled: event.target.checked })} /></label>
          </div>
          {!status.automation_controls_editable && <p className="mt-3 text-xs text-ink-400">Automation switches are administrator-only.</p>}
        </div>
        <div className="rounded-lg border border-linen-400 bg-linen-100 p-4">
          <h3 className="text-sm font-semibold text-ink-700">Queue untriaged tickets</h3><p className="mt-1 text-xs leading-5 text-ink-500">Queue only active tickets created in the selected bounded window.</p>
          <div className="mt-4 flex flex-wrap items-end gap-2"><label className="text-xs text-ink-500">Window<select className="input-base mt-1" value={windowUnit} onChange={(event) => { const unit = event.target.value as "days" | "weeks"; setWindowUnit(unit); setWindowValue(unit === "days" ? 7 : 4); }}><option value="days">Days</option><option value="weeks">Weeks</option></select></label><label className="text-xs text-ink-500">Value<input className="input-base mt-1 w-24" type="number" min={1} max={windowUnit === "days" ? 7 : 4} value={windowValue} onChange={(event) => setWindowValue(Number(event.target.value))} /></label><Button disabled={!triageWindowValid} onClick={() => setTriageConfirm(true)} leadingIcon={<ListChecks className="h-4 w-4" />}>Queue triage</Button></div>
          {triageMutation.data && <p role="status" className="mt-3 text-xs text-moss-600">Queued {triageMutation.data.queued} of {triageMutation.data.found} eligible tickets.</p>}
        </div>
      </div>}
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]" data-routing-section="rules">
      <SectionHeader title="Structured routing rules" description="Admins and supervisors can tune matching conditions and resolver recommendations. The core evidence order, output schema, confidence limits, and trust boundary are protected in code." actions={<Button size="sm" onClick={() => setEditingRule("new")} leadingIcon={<Plus className="h-4 w-4" />}>Add rule</Button>} />
      <div className="mt-5 space-y-3">
        {rulesQuery.isLoading ? <Skeleton className="h-28 w-full" /> : rulesQuery.data?.items.length ? rulesQuery.data.items.map((rule) => <div key={rule.id} className="flex flex-col gap-3 rounded-lg border border-linen-400 bg-linen-100 p-4 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-ink-700">{rule.name}</h3><Badge variant={rule.enabled ? "success" : "neutral"}>{rule.enabled ? "Active" : "Disabled"}</Badge><Badge>Priority {rule.priority}</Badge></div><p className="mt-1 text-xs text-ink-500">{rule.description || "No internal description"}</p><p className="mt-2 text-xs text-ink-500">When {rule.business_context && `context is ${rule.business_context}; `}{rule.scope && `scope is ${rule.scope}; `}{rule.service_contains && `service contains “${rule.service_contains}”; `}{rule.failure_domain_contains && `failure domain contains “${rule.failure_domain_contains}”; `}recommend <span className="font-mono text-ink-700">{rule.primary_group}</span>{rule.secondary_group ? <> with <span className="font-mono text-ink-700">{rule.secondary_group}</span></> : null}.</p></div><Button size="sm" variant="secondary" onClick={() => setEditingRule(rule)} leadingIcon={<Pencil className="h-3.5 w-3.5" />}>Edit</Button></div>) : <EmptyState icon={<Waypoints className="h-5 w-5" />} title="No custom routing rules" description="The protected core routing policy is active. Add a structured rule only when your organization needs an explicit refinement." />}
      </div>
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]" data-routing-section="agent-team-mappings">
      <SectionHeader title="Agent team mappings" description="Map each Tickety agent to one or more resolver teams. These local memberships do not alter Freshservice directory groups." />
      <div className="mt-4 flex items-center gap-2 rounded-lg border border-linen-400 bg-linen-100 px-3"><Search className="h-4 w-4 text-ink-400" /><input aria-label="Search agents" className="min-h-10 w-full bg-transparent text-sm outline-none" value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} placeholder="Search by agent name" /></div>
      <div className="mt-4 divide-y divide-linen-400 overflow-hidden rounded-lg border border-linen-400">
        {mappingsQuery.isLoading ? <Skeleton className="h-28 w-full" /> : mappings?.items.map((agent) => <div key={agent.user_id} className="flex flex-col gap-3 bg-linen-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex items-center gap-2"><span className="text-sm font-semibold text-ink-700">{agent.user_name}</span><Badge>{agent.role}</Badge></div><div className="mt-2 flex flex-wrap gap-1.5">{agent.resolver_groups.length ? agent.resolver_groups.map((group) => <Badge key={group} variant="info">{resolverGroupByCode.get(group)?.label ?? group}</Badge>) : <span className="text-xs text-ink-400">No local resolver team mapping</span>}</div></div>{mappings.editable && <Button size="sm" variant="secondary" onClick={() => setEditingAgent(agent)}>Edit teams</Button>}</div>)}
      </div>
      {mappings && <div className="mt-4 flex items-center justify-between text-xs text-ink-500"><span>{mappings.total} active operational users</span><div className="flex gap-2"><Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</Button><Button size="sm" variant="secondary" disabled={!mappings.has_more} onClick={() => setOffset(offset + 50)}>Next</Button></div></div>}
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]" data-routing-section="catalog-mapping-pending">
      <SectionHeader title="Catalog mapping recommendations" description="Recommendation only · catalog mapping pending. Tickety does not apply provider group mappings from this view." />
      {catalogQuery.isLoading ? <Skeleton className="mt-4 h-24 w-full" /> : catalogQuery.data?.recommendations.length ? <div className="mt-4 grid gap-3 md:grid-cols-2">{catalogQuery.data.recommendations.map((item) => <div key={`${item.scope.binding_id}-${item.scope.workspace_id}-${item.resolver_code}`} className="rounded-lg border border-linen-400 bg-linen-100 p-4"><div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-moss-600" /><span className="font-mono text-xs text-ink-700">{item.resolver_code}</span></div><p className="mt-2 text-sm text-ink-600">Recommended provider group: <strong>{item.provider_group_name}</strong></p><p className="mt-1 text-xs text-ink-400">{Math.round(item.confidence * 100)}% confidence · {item.evidence_ticket_count} tickets · {item.distinct_agent_count} agents</p></div>)}</div> : <Alert className="mt-4" variant="info" title="No recommendation is ready">More trusted ticket history and provider membership evidence are needed before suggesting a catalog mapping.</Alert>}
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]">
      <SectionHeader title="Resolver taxonomy" description="The closed set available to AI routing, custom rules, and agent membership mappings." />
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{resolverGroupCatalog.map((group) => <div key={group.code} className="rounded-lg border border-linen-400 bg-linen-100 p-4"><div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-ink-700">{group.label}</span><Badge>{group.domain}</Badge></div><code className="mt-2 block text-[11px] text-semantic-primary">{group.code}</code><p className="mt-2 text-xs leading-5 text-ink-500">{group.description}</p></div>)}</div>
    </section>

    <ConfirmDialog open={triageConfirm} onOpenChange={setTriageConfirm} title="Queue untriaged tickets?" description={`This will queue eligible active tickets from the selected ${windowValue} ${windowUnit}. Existing completed triage will not be replaced.`} confirmLabel="Queue triage" onConfirm={async () => { await triageMutation.mutateAsync(); }} pending={triageMutation.isPending} />
    {editingAgent && <AgentMappingDialog agent={editingAgent} onClose={() => setEditingAgent(null)} onSaved={() => { setEditingAgent(null); void queryClient.invalidateQueries({ queryKey: ["routing", "agent-team-mappings"] }); }} />}
    {editingRule && <RoutingRuleDialog rule={editingRule === "new" ? null : editingRule} onClose={() => setEditingRule(null)} onSaved={() => { setEditingRule(null); void queryClient.invalidateQueries({ queryKey: ["routing", "rules"] }); }} />}
  </PageFrame>;
}

function StatusCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-linen-400 bg-linen-50 p-4 shadow-[var(--shadow-card)]"><p className="font-mono text-[10px] uppercase tracking-wider text-ink-400">{label}</p><p className="mt-2 text-xl font-semibold text-ink-700">{value}</p><p className="mt-1 text-xs text-ink-500">{detail}</p></div>;
}

function AgentMappingDialog({ agent, onClose, onSaved }: { agent: AgentTeamMapping; onClose: () => void; onSaved: () => void }) {
  const [selected, setSelected] = useState<ResolverGroup[]>(agent.resolver_groups);
  const mutation = useMutation({ mutationFn: () => api.updateAgentTeamMapping(agent.user_id, selected, agent.resolver_groups), onSuccess: onSaved });
  const toggle = (group: ResolverGroup) => setSelected((current) => current.includes(group) ? current.filter((item) => item !== group) : [...current, group]);
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }} title={`Teams for ${agent.user_name}`} description="Select any number of local resolver teams. This does not write provider directory membership." footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button pending={mutation.isPending} onClick={() => mutation.mutate()}>Save teams</Button></>}><div className="space-y-2">{resolverGroupCatalog.map((group) => <label key={group.code} className="flex cursor-pointer items-start gap-3 rounded-lg border border-linen-400 p-3"><input className="mt-1" type="checkbox" checked={selected.includes(group.code)} onChange={() => toggle(group.code)} /><span><span className="block text-sm font-semibold text-ink-700">{group.label}</span><span className="block text-xs text-ink-500">{group.description}</span></span></label>)}{mutation.isError && <Alert variant="danger" title="Mapping was not saved">Refresh the agent list and try again.</Alert>}</div></Dialog>;
}

function RoutingRuleDialog({ rule, onClose, onSaved }: { rule: RoutingRule | null; onClose: () => void; onSaved: () => void }) {
  const initial = useMemo<RoutingRuleDraft>(() => rule ? { name: rule.name, description: rule.description, enabled: rule.enabled, priority: rule.priority, business_context: rule.business_context, scope: rule.scope, service_contains: rule.service_contains, failure_domain_contains: rule.failure_domain_contains, primary_group: rule.primary_group, secondary_group: rule.secondary_group } : emptyRule, [rule]);
  const [draft, setDraft] = useState(initial);
  const hasCondition = Boolean(draft.business_context || draft.scope || draft.service_contains?.trim() || draft.failure_domain_contains?.trim());
  const mutation = useMutation({ mutationFn: () => rule ? api.updateRoutingRule(rule.id, draft, rule.version) : api.createRoutingRule(draft), onSuccess: onSaved });
  const patch = <K extends keyof RoutingRuleDraft>(key: K, value: RoutingRuleDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }} title={rule ? "Edit routing rule" : "Add routing rule"} description="Rules are structured refinements. They cannot replace Tickety's core routing contract or trust boundary." className="max-w-2xl" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!hasCondition || !draft.name.trim()} pending={mutation.isPending} onClick={() => mutation.mutate()}>{rule ? "Save rule" : "Create rule"}</Button></>}><div className="grid gap-4 sm:grid-cols-2"><label className="text-xs text-ink-500 sm:col-span-2">Rule name<input className="input-base mt-1" value={draft.name} maxLength={80} onChange={(event) => patch("name", event.target.value)} /></label><label className="text-xs text-ink-500 sm:col-span-2">Description<input className="input-base mt-1" value={draft.description ?? ""} maxLength={240} onChange={(event) => patch("description", event.target.value || null)} /></label><label className="text-xs text-ink-500">Priority<input className="input-base mt-1" type="number" min={1} max={1000} value={draft.priority} onChange={(event) => patch("priority", Number(event.target.value))} /></label><label className="flex items-center gap-2 self-end pb-2 text-sm text-ink-600"><input type="checkbox" checked={draft.enabled} onChange={(event) => patch("enabled", event.target.checked)} />Rule enabled</label><label className="text-xs text-ink-500">Business context<select className="input-base mt-1" value={draft.business_context ?? ""} onChange={(event) => patch("business_context", (event.target.value || null) as RoutingRuleDraft["business_context"])}><option value="">Any</option><option value="ALMO">ALMO</option><option value="JAM">JAM</option><option value="UNKNOWN">Unknown</option></select></label><label className="text-xs text-ink-500">Impact scope<select className="input-base mt-1" value={draft.scope ?? ""} onChange={(event) => patch("scope", (event.target.value || null) as RoutingRuleDraft["scope"])}><option value="">Any</option><option value="single_user">Single user</option><option value="multiple_users">Multiple users</option><option value="service_wide">Service wide</option><option value="unknown">Unknown</option></select></label><label className="text-xs text-ink-500">Affected service contains<input className="input-base mt-1" value={draft.service_contains ?? ""} maxLength={80} onChange={(event) => patch("service_contains", event.target.value || null)} /></label><label className="text-xs text-ink-500">Failure domain contains<input className="input-base mt-1" value={draft.failure_domain_contains ?? ""} maxLength={80} onChange={(event) => patch("failure_domain_contains", event.target.value || null)} /></label><label className="text-xs text-ink-500">Primary resolver group<select className="input-base mt-1" value={draft.primary_group} onChange={(event) => patch("primary_group", event.target.value as ResolverGroup)}>{resolverGroupCatalog.map((group) => <option key={group.code} value={group.code}>{group.label}</option>)}</select></label><label className="text-xs text-ink-500">Secondary group<select className="input-base mt-1" value={draft.secondary_group ?? ""} onChange={(event) => patch("secondary_group", (event.target.value || null) as ResolverGroup | null)}><option value="">None</option>{resolverGroupCatalog.filter((group) => group.code !== "INFRA_HELPDESK" && group.code !== draft.primary_group).map((group) => <option key={group.code} value={group.code}>{group.label}</option>)}</select></label></div>{!hasCondition && <Alert className="mt-4" variant="warning" title="Add at least one match condition">A global unconditional override is not allowed.</Alert>}{mutation.isError && <Alert className="mt-4" variant="danger" title="Rule was not saved">Check the structured fields or refresh if another editor changed this rule.</Alert>}</Dialog>;
}
