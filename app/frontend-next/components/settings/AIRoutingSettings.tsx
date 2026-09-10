"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ListChecks, PauseCircle, Pencil, PlayCircle, Plus, Search, Sparkles, Waypoints } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, Dialog, EmptyState, Skeleton } from "@/components/ui";
import { SectionHeader, SummaryStrip } from "@/components/layout/PageLayout";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence, canUseAdministrativeFeatures } from "@/lib/auth";
import { resolverGroupByCode, resolverGroupCatalog } from "@/lib/resolver-groups";
import type { AIBatchMode, AIBatchScope, AgentTeamMapping, AgentTeamMappingRecommendation, DirectoryPerson, ResolverGroup, RoutingRule, RoutingRuleDraft } from "@/lib/types";

const emptyRule: RoutingRuleDraft = {
  name: "",
  description: null,
  enabled: true,
  priority: 100,
  scope: null,
  service_contains: null,
  failure_domain_contains: null,
  primary_group: "SERVICE_DESK",
  secondary_group: null,
};

export function AIRoutingSettings() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [editingAgent, setEditingAgent] = useState<AgentTeamMapping | null>(null);
  const [editingPerson, setEditingPerson] = useState<DirectoryPerson | null>(null);
  const [proposedGroup, setProposedGroup] = useState<ResolverGroup | null>(null);
  const [editingRule, setEditingRule] = useState<RoutingRule | null | "new">(null);
  const [recommendationWindowDays, setRecommendationWindowDays] = useState(30);
  const [recommendationWindowDraft, setRecommendationWindowDraft] = useState(30);
  const [batchConfirm, setBatchConfirm] = useState(false);
  const [batchScope, setBatchScope] = useState<AIBatchScope>("four_weeks");
  const [batchMode, setBatchMode] = useState<AIBatchMode>("routing_triage");
  const [batchLimit, setBatchLimit] = useState(500);
  const [costAcknowledged, setCostAcknowledged] = useState(false);
  const [admissionConfirm, setAdmissionConfirm] = useState<"enable" | "pause" | null>(null);

  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const isAdmin = canUseAdministrativeFeatures(authQuery.data);
  const canAccessRouting = canAccessProtectedIntelligence(authQuery.data);
  const syncStatusQuery = useQuery({
    queryKey: ["sync-status"],
    queryFn: api.getSyncStatus,
    enabled: isAdmin,
  });
  const statusQuery = useQuery({ queryKey: ["routing", "status"], queryFn: api.getRoutingTriageStatus, enabled: canAccessRouting });
  const directoryEnabled = Boolean(statusQuery.data?.directory_people_read_enabled);
  const mappingsQuery = useQuery({
    queryKey: ["routing", "agent-team-mappings", search, offset],
    queryFn: () => api.getAgentTeamMappings({ search, active: true, limit: 50, offset }),
    enabled: canAccessRouting && statusQuery.isSuccess && !directoryEnabled,
  });
  const directoryQuery = useQuery({
    queryKey: ["routing", "directory-people", "agent", search, offset],
    queryFn: () => api.getDirectoryPeople({ search, active: true, sourceType: "agent", limit: 50, offset }),
    enabled: canAccessRouting && statusQuery.isSuccess && directoryEnabled,
  });
  const mappingRecommendationsQuery = useQuery({
    queryKey: ["routing", "agent-team-mapping-recommendations", recommendationWindowDays],
    queryFn: () => api.getAgentTeamMappingRecommendations(recommendationWindowDays),
    enabled: canAccessRouting,
  });
  const rulesQuery = useQuery({ queryKey: ["routing", "rules"], queryFn: api.getRoutingRules, enabled: canAccessRouting });
  const catalogQuery = useQuery({ queryKey: ["routing", "catalog-recommendations"], queryFn: api.getRoutingCatalogRecommendations, enabled: canAccessRouting });
  const batchPreviewQuery = useQuery({
    queryKey: ["routing", "ai-batch-preview", batchScope, batchMode],
    queryFn: () => api.getAIBatchPreview(batchScope, batchMode),
    enabled: isAdmin,
  });

  const batchMutation = useMutation({
    mutationFn: () => api.queueAIBatch({
      scope: batchScope,
      mode: batchMode,
      limit: batchLimit,
      acknowledge_cost: costAcknowledged,
    }),
    onSuccess: () => {
      setBatchConfirm(false);
      void queryClient.invalidateQueries({ queryKey: ["routing", "ai-batch-preview"] });
    },
  });
  const admissionMutation = useMutation({
    mutationFn: (action: "enable" | "pause") => {
      const generation = syncStatusQuery.data?.automatic_ai_generation ?? 0;
      return action === "enable"
        ? api.enableAutomaticAI(generation)
        : api.pauseAutomaticAI(generation);
    },
    onSuccess: () => {
      setAdmissionConfirm(null);
      void queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-status"] });
    },
  });
  const status = statusQuery.data;
  const mappings = mappingsQuery.data;
  const directory = directoryQuery.data;
  const peopleItems = directoryEnabled ? directory?.items : mappings?.items;
  const mappedPeople = peopleItems?.filter((item) => item.resolver_groups.length > 0).length ?? 0;
  const mappingRecommendations = useMemo(
    () => mappingRecommendationsQuery.data?.recommendations ?? [],
    [mappingRecommendationsQuery.data],
  );
  const recommendationByUser = useMemo(() => new Map(
    mappingRecommendations
      .filter((item) => item.user_id)
      .map((item) => [item.user_id as string, item]),
  ), [mappingRecommendations]);
  const recommendationByPerson = useMemo(() => new Map(
    mappingRecommendations
      .filter((item) => item.person_id)
      .map((item) => [item.person_id as string, item]),
  ), [mappingRecommendations]);
  const recommendedPeopleQueries = useQueries({
    queries: directoryEnabled
      ? mappingRecommendations
        .filter((item) => item.person_id)
        .map((item) => ({
          queryKey: ["routing", "directory-person", item.person_id],
          queryFn: () => api.getDirectoryPerson(item.person_id as string),
          staleTime: 30_000,
        }))
      : [],
  });
  const recommendedPeople = recommendedPeopleQueries.flatMap((query) => query.data ? [query.data] : []);
  const recommendedPeopleLoading = recommendedPeopleQueries.some((query) => query.isLoading);
  const recommendedPeopleError = recommendedPeopleQueries.some((query) => query.isError);
  const batchPreview = batchPreviewQuery.data;
  const syncStatus = syncStatusQuery.data;
  const automaticRoutingRunning = Boolean(
    status?.auto_routing.effective && syncStatus?.automatic_ai_enabled,
  );
  const automaticTriageRunning = Boolean(
    status?.auto_triage.effective && syncStatus?.automatic_ai_enabled,
  );
  const automaticRoutingLabel = isAdmin ? (automaticRoutingRunning ? "Running" : "Paused") : (status?.auto_routing.effective ? "Configured" : "Off");
  const automaticTriageLabel = isAdmin ? (automaticTriageRunning ? "Running" : "Paused") : (status?.auto_triage.effective ? "Configured" : "Off");
  const batchLimitValid = Number.isInteger(batchLimit) && batchLimit >= 1 && batchLimit <= 5_000;
  const recommendationWindowValid = Number.isInteger(recommendationWindowDraft) && recommendationWindowDraft >= 7 && recommendationWindowDraft <= 365;
  const batchReady = batchLimitValid
    && Boolean(batchPreview?.eligible_tickets)
    && (!batchPreview?.requires_cost_acknowledgement || costAcknowledged);
  const canMapPerson = (person: DirectoryPerson) => Boolean(
    person.local_active
    || (status?.remote_agent_team_eligible && person.source_types.includes("freshservice_agent"))
    || (status?.remote_requester_team_eligible && person.source_types.includes("freshservice_requester"))
  );

  if (authQuery.isLoading) return <Skeleton className="h-96 w-full" />;
  if (authQuery.isError) return <Alert variant="danger" title="Routing access could not be checked">Retry after confirming your session is available.</Alert>;
  if (!canAccessRouting) return <Alert variant="warning" title="Administrator or supervisor access required">Routing and triage controls are available only to authenticated operational leaders.</Alert>;

  return <div id="settings-routing" className="scroll-mt-36 space-y-8">
    <SummaryStrip label="Routing and triage status">
      <StatusCard label="Auto-triage" value={automaticTriageLabel} detail={status?.auto_triage.effective ? (isAdmin ? "AI classification follows the source admission boundary" : "Global triage is configured; admission status is administrator-only") : "The global triage feature is off"} />
      <StatusCard label="Auto-routing" value={automaticRoutingLabel} detail={status?.auto_routing.effective ? (isAdmin ? "Advisory output; provider assignments stay read-only" : "Global routing is configured; admission status is administrator-only") : "The global routing feature is off"} />
      <StatusCard label="Agent mapping review" value={`${mappingRecommendations.length} ready`} detail={directoryEnabled ? `${directory?.total ?? 0} active agents · ${mappedPeople} mapped on this page` : `${mappings?.total ?? 0} operational users · ${mappedPeople} mapped on this page`} />
      <StatusCard label="Catalog mapping" value="Pending" detail={`${catalogQuery.data?.recommendations.length ?? 0} recommendation(s) ready`} />
    </SummaryStrip>

    {(statusQuery.isError || syncStatusQuery.isError || mappingsQuery.isError || directoryQuery.isError || mappingRecommendationsQuery.isError || recommendedPeopleError || rulesQuery.isError) && <Alert variant="danger" title="Some routing controls are unavailable">Refresh the page before making changes.</Alert>}

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]">
      <SectionHeader title="AI processing" description="New active tickets are processed automatically from newest to oldest for four weeks. Older tickets remain manual so provider usage stays under administrator control." />
      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.9fr)]">
        <div className="rounded-lg border border-linen-400 bg-linen-100 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-ink-700">Automatic lane</h3>
              <p className="mt-1 text-xs text-ink-500">{syncStatusQuery.isLoading ? "Checking integration admission…" : syncStatus?.automatic_ai_enabled ? `Active for ${syncStatus.provider}` : "Not admitting tickets to AI"}</p>
            </div>
            {isAdmin && syncStatus && <Button size="sm" variant={syncStatus.automatic_ai_enabled ? "secondary" : "primary"} pending={admissionMutation.isPending} onClick={() => setAdmissionConfirm(syncStatus.automatic_ai_enabled ? "pause" : "enable")} leadingIcon={syncStatus.automatic_ai_enabled ? <PauseCircle className="h-4 w-4" /> : <PlayCircle className="h-4 w-4" />}>{syncStatus.automatic_ai_enabled ? "Pause automatic AI" : "Start automatic AI"}</Button>}
          </div>
          <p className="mt-2 text-sm leading-6 text-ink-500">The latest four weeks are admitted automatically. Each sweep reserves all available capacity for the newest tickets; older downloaded history is never admitted without an admin batch.</p>
          <div className="mt-4 flex flex-wrap gap-2"><Badge variant={syncStatus?.automatic_ai_enabled ? "success" : "warning"}>{syncStatus?.automatic_ai_enabled ? "Admission active" : "Admission paused"}</Badge><Badge>28-day window</Badge><Badge>Newest first</Badge><Badge>Historical AI manual</Badge></div>
          {status?.auto_routing.effective && syncStatus && !syncStatus.automatic_ai_enabled && <Alert className="mt-4" variant="warning" title="Routing is configured but not running">Start automatic AI to process the newest active tickets. Historical tickets remain excluded.</Alert>}
          {admissionMutation.isError && <Alert className="mt-4" variant="danger" title="Automatic AI was not changed">Refresh sync status and try again. A successful source sync is required before activation.</Alert>}
        </div>
        {!authQuery.isLoading && !isAdmin ? <Alert variant="info" title="Admin batch controls">Only administrators can queue historical AI work or accept provider token charges.</Alert> : <div className="rounded-lg border border-linen-400 bg-linen-100 p-4">
          <h3 className="text-sm font-semibold text-ink-700">Administrator batch</h3>
          <p className="mt-1 text-xs leading-5 text-ink-500">Choose any time range. Tickets are queued from newest to oldest and existing current AI artifacts are preserved.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-ink-500">Time range<select className="input-base mt-1" value={batchScope} onChange={(event) => { setBatchScope(event.target.value as AIBatchScope); setCostAcknowledged(false); }}><option value="four_weeks">Latest 4 weeks</option><option value="three_months">Latest 3 months</option><option value="six_months">Latest 6 months</option><option value="one_year">Latest year</option><option value="all_time">All time</option></select></label>
            <label className="text-xs text-ink-500">AI work<select className="input-base mt-1" value={batchMode} onChange={(event) => { setBatchMode(event.target.value as AIBatchMode); setCostAcknowledged(false); }}><option value="routing_triage">Routing and triage</option><option value="full_analysis">Full analysis</option></select></label>
            <label className="text-xs text-ink-500">Tickets this batch<input className="input-base mt-1" type="number" min={1} max={5_000} value={batchLimit} onChange={(event) => { setBatchLimit(Number(event.target.value)); setCostAcknowledged(false); }} /></label>
          </div>
          {batchPreviewQuery.isLoading ? <Skeleton className="mt-4 h-20 w-full" /> : batchPreviewQuery.isError ? <Alert className="mt-4" variant="danger" title="Batch estimate unavailable">Refresh before queueing AI work.</Alert> : batchPreview && <div className="mt-4 space-y-3">
            <div className="grid grid-cols-3 gap-2 text-center"><Metric label="Eligible" value={batchPreview.eligible_tickets.toLocaleString()} /><Metric label="Provider calls" value={batchPreview.estimated_provider_calls.toLocaleString()} /><Metric label="Est. tokens" value={batchPreview.estimated_tokens.toLocaleString()} /></div>
            {batchPreview.requires_cost_acknowledgement && <Alert variant="warning" title="Provider charges may apply">This selection can consume a material number of provider tokens. The estimate covers all eligible tickets; this run queues at most {batchLimit.toLocaleString()}.</Alert>}
            {batchPreview.requires_cost_acknowledgement && <label className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><input className="mt-1" type="checkbox" checked={costAcknowledged} onChange={(event) => setCostAcknowledged(event.target.checked)} /><span>I understand this batch consumes provider tokens and may incur charges.</span></label>}
            <Button disabled={!batchReady} onClick={() => setBatchConfirm(true)} leadingIcon={<ListChecks className="h-4 w-4" />}>Queue AI batch</Button>
          </div>}
          {batchMutation.data && <p role="status" className="mt-3 text-xs text-moss-600">Queued {batchMutation.data.queued.toLocaleString()} ticket(s); {batchMutation.data.remaining.toLocaleString()} remain in this range.</p>}
          {batchMutation.isError && <Alert className="mt-3" variant="danger" title="Batch was not queued">Refresh the estimate and confirm provider cost before trying again.</Alert>}
        </div>}
      </div>
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]" data-routing-section="rules">
      <SectionHeader title="Structured routing rules" description="Administrators and supervisors can tune matching conditions and resolver recommendations here. The core evidence order, output schema, confidence limits, and trust boundary are protected in code." actions={<Button size="sm" onClick={() => setEditingRule("new")} leadingIcon={<Plus className="h-4 w-4" />}>Add rule</Button>} />
      <div className="mt-5 space-y-3">
        {rulesQuery.isLoading ? <Skeleton className="h-28 w-full" /> : rulesQuery.data?.items.length ? rulesQuery.data.items.map((rule) => <div key={rule.id} className="flex flex-col gap-3 rounded-lg border border-linen-400 bg-linen-100 p-4 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-ink-700">{rule.name}</h3><Badge variant={rule.enabled ? "success" : "neutral"}>{rule.enabled ? "Active" : "Disabled"}</Badge><Badge>Priority {rule.priority}</Badge></div><p className="mt-1 text-xs text-ink-500">{rule.description || "No internal description"}</p><p className="mt-2 text-xs text-ink-500">When {rule.scope && `scope is ${rule.scope}; `}{rule.service_contains && `service contains “${rule.service_contains}”; `}{rule.failure_domain_contains && `failure domain contains “${rule.failure_domain_contains}”; `}recommend <span className="font-mono text-ink-700">{rule.primary_group}</span>{rule.secondary_group ? <> with <span className="font-mono text-ink-700">{rule.secondary_group}</span></> : null}.</p></div><Button size="sm" variant="secondary" onClick={() => setEditingRule(rule)} leadingIcon={<Pencil className="h-3.5 w-3.5" />}>Edit</Button></div>) : <EmptyState icon={<Waypoints className="h-5 w-5" />} title="No custom routing rules" description="The protected core routing policy is active. Add a structured rule only when your organization needs an explicit refinement." />}
      </div>
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]" data-routing-section={directoryEnabled ? "directory-people" : "agent-team-mappings"}>
      <SectionHeader title="Agent and team mappings" description="Review AI-informed team recommendations derived from each agent's trusted routed ticket history. Recommendations never change a mapping until an administrator saves it." />
      <div className="mt-4 rounded-lg border border-linen-400 bg-linen-100 px-3 py-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {mappingRecommendationsQuery.isLoading ? <Skeleton className="h-8 w-full" /> : mappingRecommendationsQuery.data && <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500"><Sparkles className="h-4 w-4 text-semantic-primary" /><span>{mappingRecommendationsQuery.data.coverage.recommended_subject_count} recommendation(s) from {mappingRecommendationsQuery.data.coverage.attributed_ticket_count.toLocaleString()} trusted agent-ticket assignments in the last {mappingRecommendationsQuery.data.window_days} days.</span><Badge>Advisory only</Badge></div>}
          {isAdmin ? <div className="flex shrink-0 items-end gap-2"><label className="text-[11px] text-ink-500">Evidence window<input aria-label="Recommendation evidence window in days" className="input-base mt-1 w-24" type="number" min={7} max={365} value={recommendationWindowDraft} onChange={(event) => setRecommendationWindowDraft(Number(event.target.value))} /></label><Button size="sm" variant="secondary" disabled={!recommendationWindowValid || recommendationWindowDraft === recommendationWindowDays} onClick={() => setRecommendationWindowDays(recommendationWindowDraft)}>Apply window</Button></div> : <Badge>30-day window</Badge>}
        </div>
        <p className="mt-2 text-[11px] text-ink-400">Uses existing trusted AI routing output only; changing this window does not call the AI provider or consume tokens.</p>
      </div>
      {directoryEnabled && <div className="mt-4">
        <h3 className="text-sm font-semibold text-ink-700">Recommendations needing review</h3>
        <p className="mt-1 text-xs text-ink-500">Only recommendations backed by a clear majority of trusted recent ticket assignments appear here.</p>
        <div className="mt-3 divide-y divide-linen-400 overflow-hidden rounded-lg border border-linen-400">
          {(mappingRecommendationsQuery.isLoading || recommendedPeopleLoading) ? <Skeleton className="h-28 w-full" /> : recommendedPeople.length ? recommendedPeople.map((person) => <DirectoryPersonRow key={person.id} person={person} recommendation={recommendationByPerson.get(person.id) ?? (person.user_id ? recommendationByUser.get(person.user_id) : undefined)} editable={Boolean(directory?.editable) && canMapPerson(person)} onEdit={(recommendedGroup) => { setProposedGroup(recommendedGroup ?? null); setEditingPerson(person); }} />) : <EmptyState icon={<CheckCircle2 className="h-5 w-5" />} title="No agent mapping review needed" description="No trusted-history recommendation currently clears the evidence threshold." />}
        </div>
      </div>}
      <details className="group mt-4 rounded-lg border border-linen-400 bg-linen-50">
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-4 py-3 text-sm font-semibold text-ink-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] [&::-webkit-details-marker]:hidden"><span>Browse all active agents</span><Badge>{directoryEnabled ? directory?.total ?? 0 : mappings?.total ?? 0}</Badge></summary>
        <div className="border-t border-linen-400 p-4">
          <div className="flex items-center gap-2 rounded-lg border border-linen-400 bg-linen-100 px-3"><Search className="h-4 w-4 text-ink-400" /><input aria-label="Search agents" className="min-h-10 w-full bg-transparent text-sm outline-none" value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} placeholder="Search by agent name, email, or external ID" /></div>
          <div className="mt-4 divide-y divide-linen-400 overflow-hidden rounded-lg border border-linen-400">
            {(statusQuery.isLoading || mappingsQuery.isLoading || directoryQuery.isLoading || mappingRecommendationsQuery.isLoading) ? <Skeleton className="h-28 w-full" /> : directoryEnabled ? directory?.items.map((person) => <DirectoryPersonRow key={person.id} person={person} editable={directory.editable && canMapPerson(person)} onEdit={(recommendedGroup) => { setProposedGroup(recommendedGroup ?? null); setEditingPerson(person); }} />) : mappings?.items.map((agent) => <AgentMappingRow key={agent.user_id} agent={agent} recommendation={recommendationByUser.get(agent.user_id)} editable={mappings.editable} onEdit={(recommendedGroup) => { setProposedGroup(recommendedGroup ?? null); setEditingAgent(agent); }} />)}
          </div>
          {(directoryEnabled ? directory : mappings) && <div className="mt-4 flex items-center justify-between text-xs text-ink-500"><span>{directoryEnabled ? `${directory?.total ?? 0} active agents` : `${mappings?.total ?? 0} active operational users`}</span><div className="flex gap-2"><Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</Button><Button size="sm" variant="secondary" disabled={directoryEnabled ? !directory?.has_more : !mappings?.has_more} onClick={() => setOffset(offset + 50)}>Next</Button></div></div>}
        </div>
      </details>
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]" data-routing-section="catalog-mapping-pending">
      <SectionHeader title="Catalog mapping recommendations" description="Recommendation only · catalog mapping pending. Tickety does not apply provider group mappings from this view." />
      {catalogQuery.isLoading ? <Skeleton className="mt-4 h-24 w-full" /> : catalogQuery.data?.recommendations.length ? <div className="mt-4 grid gap-3 md:grid-cols-2">{catalogQuery.data.recommendations.map((item) => <div key={`${item.scope.binding_id}-${item.scope.workspace_id}-${item.resolver_code}`} className="rounded-lg border border-linen-400 bg-linen-100 p-4"><div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-moss-600" /><span className="font-mono text-xs text-ink-700">{item.resolver_code}</span></div><p className="mt-2 text-sm text-ink-600">Recommended provider group: <strong>{item.provider_group_name}</strong></p><p className="mt-1 text-xs text-ink-400">{Math.round(item.confidence * 100)}% confidence · {item.evidence_ticket_count} tickets · {item.distinct_agent_count} agents</p></div>)}</div> : <Alert className="mt-4" variant="info" title="No recommendation is ready">More trusted ticket history and provider membership evidence are needed before suggesting a catalog mapping.</Alert>}
    </section>

    <section className="rounded-xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-card)]">
      <SectionHeader title="Resolver taxonomy" description="The closed set available to AI routing, custom rules, and agent membership mappings." />
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{resolverGroupCatalog.map((group) => <div key={group.code} className="rounded-lg border border-linen-400 bg-linen-100 p-4"><div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-ink-700">{group.label}</span><Badge>{group.domain}</Badge></div><code className="mt-2 block text-[11px] text-semantic-primary">{group.code}</code><p className="mt-2 text-xs leading-5 text-ink-500">{group.description}</p></div>)}</div>
    </section>

    <ConfirmDialog open={batchConfirm} onOpenChange={setBatchConfirm} title="Queue AI batch?" description={`Queue up to ${batchLimit.toLocaleString()} eligible ticket(s) from ${batchScope.replaceAll("_", " ")}, newest first. Current AI artifacts will not be replaced.`} confirmLabel="Queue batch" onConfirm={async () => { await batchMutation.mutateAsync(); }} pending={batchMutation.isPending} />
    <ConfirmDialog open={admissionConfirm !== null} onOpenChange={(open) => { if (!open) setAdmissionConfirm(null); }} title={admissionConfirm === "pause" ? "Pause automatic AI?" : "Start automatic AI?"} description={admissionConfirm === "pause" ? "New tickets will stop entering AI and active claims will be revoked. You can resume later without moving the original audit boundary." : "The newest active tickets from the latest four weeks will enter AI from newest to oldest. Older tickets remain manual."} confirmLabel={admissionConfirm === "pause" ? "Pause automatic AI" : "Start automatic AI"} destructive={admissionConfirm === "pause"} onConfirm={async () => { if (admissionConfirm) await admissionMutation.mutateAsync(admissionConfirm); }} pending={admissionMutation.isPending} />
    {editingAgent && <AgentMappingDialog agent={editingAgent} proposedGroup={proposedGroup} onClose={() => { setEditingAgent(null); setProposedGroup(null); }} onSaved={() => { setEditingAgent(null); setProposedGroup(null); void queryClient.invalidateQueries({ queryKey: ["routing", "agent-team-mappings"] }); }} />}
    {editingPerson && <DirectoryPersonMappingDialog person={editingPerson} proposedGroup={proposedGroup} onClose={() => { setEditingPerson(null); setProposedGroup(null); }} onSaved={() => { setEditingPerson(null); setProposedGroup(null); void queryClient.invalidateQueries({ queryKey: ["routing", "directory-people"] }); }} />}
    {editingRule && <RoutingRuleDialog rule={editingRule === "new" ? null : editingRule} onClose={() => setEditingRule(null)} onSaved={() => { setEditingRule(null); void queryClient.invalidateQueries({ queryKey: ["routing", "rules"] }); }} />}
  </div>;
}

function MappingRecommendation({ recommendation, currentGroups, editable, onReview }: { recommendation?: AgentTeamMappingRecommendation; currentGroups: ResolverGroup[]; editable: boolean; onReview: () => void }) {
  if (!recommendation) return null;
  const alreadyMapped = currentGroups.includes(recommendation.resolver_group);
  const groupLabel = resolverGroupByCode.get(recommendation.resolver_group)?.label ?? recommendation.resolver_group;
  return <div className="mt-3 flex flex-col gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><Sparkles className="h-3.5 w-3.5 text-sky-700" /><span className="text-xs font-semibold text-sky-900">History recommendation</span><Badge variant={alreadyMapped ? "success" : "info"}>{groupLabel}</Badge>{alreadyMapped && <Badge variant="success">Matches mapping</Badge>}</div><p className="mt-1 text-xs leading-5 text-sky-800">{recommendation.evidence_ticket_count} of {recommendation.total_trusted_ticket_count} trusted AI-routed assignments ({Math.round(recommendation.group_share * 100)}%) · {Math.round(recommendation.confidence * 100)}% conservative confidence</p></div>{!alreadyMapped && (editable ? <Button size="sm" variant="secondary" onClick={onReview}>Review recommendation</Button> : <span className="text-[11px] text-sky-800">Administrator approval required</span>)}</div>;
}

function AgentMappingRow({ agent, recommendation, editable, onEdit }: { agent: AgentTeamMapping; recommendation?: AgentTeamMappingRecommendation; editable: boolean; onEdit: (recommendedGroup?: ResolverGroup) => void }) {
  return <div className="bg-linen-50 p-4"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex items-center gap-2"><span className="text-sm font-semibold text-ink-700">{agent.user_name}</span><Badge>{agent.role}</Badge></div><div className="mt-2 flex flex-wrap gap-1.5">{agent.resolver_groups.length ? agent.resolver_groups.map((group) => <Badge key={group} variant="info">{resolverGroupByCode.get(group)?.label ?? group}</Badge>) : <span className="text-xs text-ink-400">No local resolver team mapping</span>}</div></div>{editable && <Button size="sm" variant="secondary" onClick={() => onEdit()}>Edit teams</Button>}</div><MappingRecommendation recommendation={recommendation} currentGroups={agent.resolver_groups} editable={editable} onReview={() => recommendation && onEdit(recommendation.resolver_group)} /></div>;
}

function DirectoryPersonRow({ person, recommendation, editable, onEdit }: { person: DirectoryPerson; recommendation?: AgentTeamMappingRecommendation; editable: boolean; onEdit: (recommendedGroup?: ResolverGroup) => void }) {
  const labels = person.source_types.map((source) => source === "local" ? "Tickety" : source === "freshservice_agent" ? "Freshservice agent" : "Freshservice requester");
  const agentIdentities = person.identities.filter((identity) => identity.user_type === "agent");
  const sharedSupportEmail = /^(helpdesk|support|service[._-]?desk|it[._-]?support)@/i.test(person.email ?? "");
  return <div className="bg-linen-50 p-4"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-ink-700">{person.name}</span>{labels.map((label) => <Badge key={label} variant={label === "Tickety" ? "neutral" : "info"}>{label}</Badge>)}{person.linked && <Badge variant="success">Linked</Badge>}{!person.effective_active && <Badge variant="warning">Inactive</Badge>}</div>{person.email && <p className="mt-1 text-xs text-ink-500">{sharedSupportEmail ? "Shared reply address · " : ""}{person.email}</p>}{agentIdentities.length > 0 && <p className="mt-1 font-mono text-[11px] text-ink-400">Provider agent ID {agentIdentities.map((identity) => identity.external_id).join(", ")}</p>}<div className="mt-2 flex flex-wrap gap-1.5">{person.resolver_groups.length ? person.resolver_groups.map((group) => <Badge key={group} variant="info">{resolverGroupByCode.get(group)?.label ?? group}</Badge>) : <span className="text-xs text-ink-400">No resolver team mapping</span>}</div></div>{editable && <Button size="sm" variant="secondary" onClick={() => onEdit()}>Edit teams</Button>}</div><MappingRecommendation recommendation={recommendation} currentGroups={person.resolver_groups} editable={editable} onReview={() => recommendation && onEdit(recommendation.resolver_group)} /></div>;
}

function StatusCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-linen-400 bg-linen-50 p-4 shadow-[var(--shadow-card)]"><p className="font-mono text-[10px] uppercase tracking-wider text-ink-400">{label}</p><p className="mt-2 text-xl font-semibold text-ink-700">{value}</p><p className="mt-1 text-xs text-ink-500">{detail}</p></div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-linen-400 bg-linen-50 px-2 py-3"><p className="text-base font-semibold text-ink-700">{value}</p><p className="mt-1 text-[10px] uppercase tracking-wide text-ink-400">{label}</p></div>;
}

function AgentMappingDialog({ agent, proposedGroup, onClose, onSaved }: { agent: AgentTeamMapping; proposedGroup: ResolverGroup | null; onClose: () => void; onSaved: () => void }) {
  const [selected, setSelected] = useState<ResolverGroup[]>(proposedGroup && !agent.resolver_groups.includes(proposedGroup) ? [...agent.resolver_groups, proposedGroup] : agent.resolver_groups);
  const mutation = useMutation({ mutationFn: () => api.updateAgentTeamMapping(agent.user_id, selected, agent.resolver_groups), onSuccess: onSaved });
  const toggle = (group: ResolverGroup) => setSelected((current) => current.includes(group) ? current.filter((item) => item !== group) : [...current, group]);
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }} title={`Teams for ${agent.user_name}`} description={proposedGroup ? "The trusted-history recommendation is preselected for review. Saving is still an explicit administrator decision." : "Select any number of local resolver teams. This does not write provider directory membership."} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button pending={mutation.isPending} onClick={() => mutation.mutate()}>Save teams</Button></>}><div className="space-y-2">{resolverGroupCatalog.map((group) => <label key={group.code} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${group.code === proposedGroup ? "border-sky-300 bg-sky-50" : "border-linen-400"}`}><input className="mt-1" type="checkbox" checked={selected.includes(group.code)} onChange={() => toggle(group.code)} /><span><span className="block text-sm font-semibold text-ink-700">{group.label}{group.code === proposedGroup && <span className="ml-2 text-xs font-normal text-sky-700">Recommended</span>}</span><span className="block text-xs text-ink-500">{group.description}</span></span></label>)}{mutation.isError && <Alert variant="danger" title="Mapping was not saved">Refresh the agent list and try again.</Alert>}</div></Dialog>;
}

function DirectoryPersonMappingDialog({ person, proposedGroup, onClose, onSaved }: { person: DirectoryPerson; proposedGroup: ResolverGroup | null; onClose: () => void; onSaved: () => void }) {
  const [selected, setSelected] = useState<ResolverGroup[]>(proposedGroup && !person.resolver_groups.includes(proposedGroup) ? [...person.resolver_groups, proposedGroup] : person.resolver_groups);
  const mutation = useMutation({ mutationFn: () => api.updateDirectoryPersonTeams(person.id, selected, person.resolver_groups, person.version), onSuccess: onSaved });
  const toggle = (group: ResolverGroup) => setSelected((current) => current.includes(group) ? current.filter((item) => item !== group) : [...current, group]);
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }} title={`Teams for ${person.name}`} description={proposedGroup ? "The trusted-history recommendation is preselected for review. Saving is still an explicit administrator decision." : "These memberships are local to Tickety routing. Remote people remain read-only and cannot sign in."} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button pending={mutation.isPending} onClick={() => mutation.mutate()}>Save teams</Button></>}><div className="space-y-2">{resolverGroupCatalog.map((group) => <label key={group.code} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${group.code === proposedGroup ? "border-sky-300 bg-sky-50" : "border-linen-400"}`}><input className="mt-1" type="checkbox" checked={selected.includes(group.code)} onChange={() => toggle(group.code)} /><span><span className="block text-sm font-semibold text-ink-700">{group.label}{group.code === proposedGroup && <span className="ml-2 text-xs font-normal text-sky-700">Recommended</span>}</span><span className="block text-xs text-ink-500">{group.description}</span></span></label>)}{mutation.isError && <Alert variant="danger" title="Mapping was not saved">Refresh the people list and try again.</Alert>}</div></Dialog>;
}

function RoutingRuleDialog({ rule, onClose, onSaved }: { rule: RoutingRule | null; onClose: () => void; onSaved: () => void }) {
  const initial = useMemo<RoutingRuleDraft>(() => rule ? { name: rule.name, description: rule.description, enabled: rule.enabled, priority: rule.priority, scope: rule.scope, service_contains: rule.service_contains, failure_domain_contains: rule.failure_domain_contains, primary_group: rule.primary_group, secondary_group: rule.secondary_group } : emptyRule, [rule]);
  const [draft, setDraft] = useState(initial);
  const hasCondition = Boolean(draft.scope || draft.service_contains?.trim() || draft.failure_domain_contains?.trim());
  const mutation = useMutation({ mutationFn: () => rule ? api.updateRoutingRule(rule.id, draft, rule.version) : api.createRoutingRule(draft), onSuccess: onSaved });
  const patch = <K extends keyof RoutingRuleDraft>(key: K, value: RoutingRuleDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }} title={rule ? "Edit routing rule" : "Add routing rule"} description="Rules are structured refinements. They cannot replace Tickety's core routing contract or trust boundary." className="max-w-2xl" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!hasCondition || !draft.name.trim()} pending={mutation.isPending} onClick={() => mutation.mutate()}>{rule ? "Save rule" : "Create rule"}</Button></>}><div className="grid gap-4 sm:grid-cols-2"><label className="text-xs text-ink-500 sm:col-span-2">Rule name<input className="input-base mt-1" value={draft.name} maxLength={80} onChange={(event) => patch("name", event.target.value)} /></label><label className="text-xs text-ink-500 sm:col-span-2">Description<input className="input-base mt-1" value={draft.description ?? ""} maxLength={240} onChange={(event) => patch("description", event.target.value || null)} /></label><label className="text-xs text-ink-500">Priority<input className="input-base mt-1" type="number" min={1} max={1000} value={draft.priority} onChange={(event) => patch("priority", Number(event.target.value))} /></label><label className="flex items-center gap-2 self-end pb-2 text-sm text-ink-600"><input type="checkbox" checked={draft.enabled} onChange={(event) => patch("enabled", event.target.checked)} />Rule enabled</label><label className="text-xs text-ink-500">Impact scope<select className="input-base mt-1" value={draft.scope ?? ""} onChange={(event) => patch("scope", (event.target.value || null) as RoutingRuleDraft["scope"])}><option value="">Any</option><option value="single_user">Single user</option><option value="multiple_users">Multiple users</option><option value="service_wide">Service wide</option><option value="unknown">Unknown</option></select></label><label className="text-xs text-ink-500">Affected service contains<input className="input-base mt-1" value={draft.service_contains ?? ""} maxLength={80} onChange={(event) => patch("service_contains", event.target.value || null)} /></label><label className="text-xs text-ink-500">Failure domain contains<input className="input-base mt-1" value={draft.failure_domain_contains ?? ""} maxLength={80} onChange={(event) => patch("failure_domain_contains", event.target.value || null)} /></label><label className="text-xs text-ink-500">Primary resolver group<select className="input-base mt-1" value={draft.primary_group} onChange={(event) => patch("primary_group", event.target.value as ResolverGroup)}>{resolverGroupCatalog.map((group) => <option key={group.code} value={group.code}>{group.label}</option>)}</select></label><label className="text-xs text-ink-500">Secondary group<select className="input-base mt-1" value={draft.secondary_group ?? ""} onChange={(event) => patch("secondary_group", (event.target.value || null) as ResolverGroup | null)}><option value="">None</option>{resolverGroupCatalog.filter((group) => group.code !== "SERVICE_DESK" && group.code !== draft.primary_group).map((group) => <option key={group.code} value={group.code}>{group.label}</option>)}</select></label></div>{!hasCondition && <Alert className="mt-4" variant="warning" title="Add at least one match condition">A global unconditional override is not allowed.</Alert>}{mutation.isError && <Alert className="mt-4" variant="danger" title="Rule was not saved">Check the structured fields or refresh if another editor changed this rule.</Alert>}</Dialog>;
}
