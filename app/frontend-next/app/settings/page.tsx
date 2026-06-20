"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Settings as SettingsType, LlmCatalog, LlmProvider, TicketCategory, BuildInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  Settings as SettingsIcon, Save, RefreshCw, CheckCircle2, AlertCircle,
  Users, Download, Database, Zap, Plus, Trash2, ShieldCheck, Activity,
} from "lucide-react";
import { SearchableSelect } from "@/components/ui/SearchableSelect";

const PROVIDER_OPTIONS = [
  { value: "standalone", label: "Standalone (built-in ticketing)" },
  { value: "external", label: "External ITSM provider" },
  { value: "none", label: "None (disabled)" },
];

const PROVIDER_IDS = ["deepseek", "openai", "openrouter", "azure", "azure_ai"] as const;

const CATEGORY_COLORS = [
  { value: "slate", label: "Slate", className: "bg-linen-500" },
  { value: "blue", label: "Blue", className: "bg-blue-400" },
  { value: "emerald", label: "Emerald", className: "bg-emerald-400" },
  { value: "amber", label: "Amber", className: "bg-amber-400" },
  { value: "violet", label: "Violet", className: "bg-violet-400" },
  { value: "cyan", label: "Cyan", className: "bg-cyan-400" },
  { value: "red", label: "Red", className: "bg-rust-400" },
];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const { data: catalog } = useQuery({ queryKey: ["llm-catalog"], queryFn: api.getLlmCatalog });
  const { data: version } = useQuery({ queryKey: ["version"], queryFn: api.getVersion, staleTime: Infinity });
  const { data: syncStatus } = useQuery({ queryKey: ["sync-status"], queryFn: api.getSyncStatus, refetchInterval: 30000 });

  const [form, setForm] = useState<Partial<SettingsType>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data) setForm(data); }, [data]);

  const mutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (result) => {
      setForm(result); setSaved(true);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      queryClient.invalidateQueries({ queryKey: ["llm-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      setTimeout(() => setSaved(false), 2500);
    },
  });

  const [fetchedInfo, setFetchedInfo] = useState<{ total_models: number; providers_queried: string[] } | null>(null);
  const refreshMut = useMutation({
    mutationFn: api.refreshModels,
    onSuccess: (res) => {
      setFetchedInfo({ total_models: res.total_models, providers_queried: res.providers_queried });
      queryClient.invalidateQueries({ queryKey: ["llm-catalog"] });
      queryClient.fetchQuery({ queryKey: ["llm-catalog"], queryFn: api.getLlmCatalog });
    },
  });

  const repairMut = useMutation({
    mutationFn: () => fetch("/api/admin/sync/repair", { method: "POST" }).then(r => r.json()),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["tickets"] }); },
  });

  const triageAllMut = useMutation({
    mutationFn: () => fetch("/api/admin/sync/triage-all", { method: "POST" }).then(r => r.json()),
  });

  const handleChange = (key: keyof SettingsType, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const activeProviderId = useMemo(() => {
    if (!catalog) return "deepseek";
    const model = (form.DEFAULT_MODEL || "").trim();
    if (model.startsWith("openrouter/")) return "openrouter";
    if (model.startsWith("azure_ai/")) return "azure_ai";
    if (model.startsWith("azure/")) return "azure";
    if (model.startsWith("openai/")) return "openai";
    if (model.startsWith("deepseek")) return "deepseek";
    return (catalog.current_provider as string) || "deepseek";
  }, [form.DEFAULT_MODEL, catalog]);

  const activeProvider: LlmProvider | undefined = catalog ? (catalog[activeProviderId] as LlmProvider) : undefined;

  const handleProviderChange = (pid: string) => {
    const prov = catalog ? (catalog[pid] as LlmProvider) : undefined;
    if (!prov) return;
    const firstModel = prov.models[0]?.id || (prov.model_hint ? prov.model_hint : "");
    handleChange("DEFAULT_MODEL", firstModel);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload: Record<string, string> = {};
    for (const key of Object.keys(form)) {
      const v = form[key as keyof SettingsType];
      if (typeof v !== "string" || v === "") continue;
      if (v.includes("****")) continue;
      payload[key] = v;
    }
    mutation.mutate(payload);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-ink-400">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading settings…
      </div>
    );
  }

  const itProvider = form.ITSM_PROVIDER || "standalone";

  return (
    <div className="space-y-8 max-w-3xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-linen-300 flex items-center justify-center">
          <SettingsIcon className="w-5 h-5 text-ink-600" />
        </div>
        <div>
          <h1 className="font-serif text-2xl text-ink-700">Settings</h1>
          <p className="text-sm text-ink-500">Configure LLM, ticketing, SLA, categories, and system maintenance</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* ═══ LLM Configuration ═══ */}
        <SettingsSection title="LLM Configuration" subtitle="Choose the AI provider and model for ticket triage, summarization, and resolution">
          <Field label="Provider">
            <select value={activeProviderId} onChange={(e) => handleProviderChange(e.target.value)} className="input-base">
              {PROVIDER_IDS.map((pid) => (
                <option key={pid} value={pid}>{catalog ? (catalog[pid] as LlmProvider)?.label ?? pid : pid}</option>
              ))}
            </select>
          </Field>

          <Field label="Default Model">
            {activeProvider && activeProvider.models && activeProvider.models.length > 0 ? (
              <SearchableSelect
                value={form.DEFAULT_MODEL || ""}
                options={activeProvider.models}
                onChange={(v) => handleChange("DEFAULT_MODEL", v)}
                placeholder={activeProvider.model_hint || "Select or search for a model…"}
              />
            ) : (
              <input type="text" value={form.DEFAULT_MODEL || ""} onChange={(e) => handleChange("DEFAULT_MODEL", e.target.value)} placeholder={activeProvider?.model_hint || "model id"} className="input-base" />
            )}
          </Field>

          <div className="flex items-center justify-between">
            <span className="text-xs text-ink-500">
              {fetchedInfo ? `Last fetch: ${fetchedInfo.total_models} models from ${fetchedInfo.providers_queried.length} providers` : "Model list shows built-in defaults + any previously fetched models."}
            </span>
            <button type="button" onClick={() => refreshMut.mutate()} disabled={refreshMut.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-linen-400 text-xs font-medium text-ink-600 hover:bg-linen-200 disabled:opacity-50">
              {refreshMut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              {refreshMut.isPending ? "Fetching…" : "Fetch Latest Models"}
            </button>
          </div>

          {activeProvider?.env_keys.map((ek) => (
            <Field key={ek.key} label={`${ek.label}${ek.is_set ? " ✓" : ""}`}>
              {ek.secret ? (
                <SecretInput value={(form[ek.key as keyof SettingsType] as string) || ""} onChange={(v) => handleChange(ek.key as keyof SettingsType, v)} placeholder={ek.placeholder} />
              ) : (
                <input type="text" value={(form[ek.key as keyof SettingsType] as string) || ""} onChange={(e) => handleChange(ek.key as keyof SettingsType, e.target.value)} placeholder={ek.placeholder} className="input-base" />
              )}
            </Field>
          ))}
        </SettingsSection>

        {/* ═══ Ticketing Mode ═══ */}
        <SettingsSection title="Ticketing Mode" subtitle="Choose whether Tickety uses its own built-in ticketing system or connects to an external ITSM provider">
          <Field label="Provider">
            <select value={itProvider} onChange={(e) => handleChange("ITSM_PROVIDER", e.target.value)} className="input-base">
              {PROVIDER_OPTIONS.map((p) => (<option key={p.value} value={p.value}>{p.label}</option>))}
            </select>
          </Field>

          {itProvider === "external" && (
            <>
              <Field label="Provider Domain">
                <input type="text" value={form.FRESHSERVICE_DOMAIN || ""} onChange={(e) => handleChange("FRESHSERVICE_DOMAIN", e.target.value)} placeholder="yourdomain.example.com" className="input-base" />
              </Field>
              <Field label="Provider API Key">
                <SecretInput value={form.FRESHSERVICE_API_KEY || ""} onChange={(v) => handleChange("FRESHSERVICE_API_KEY", v)} placeholder="Provider API key" />
              </Field>
              <Field label="Webhook Secret">
                <SecretInput value={form.WEBHOOK_SECRET || ""} onChange={(v) => handleChange("WEBHOOK_SECRET", v)} placeholder="Webhook shared secret" />
              </Field>
              <Field label="Sync Interval (seconds)">
                <input type="number" min={10} value={form.SYNC_INTERVAL_SECONDS || ""} onChange={(e) => handleChange("SYNC_INTERVAL_SECONDS", e.target.value)} placeholder="60" className="input-base" />
              </Field>
            </>
          )}

          {itProvider === "standalone" && (
            <div className="text-sm text-ink-500 bg-linen-200 rounded p-4 border border-linen-300">
              <p className="font-medium text-ink-600 mb-1">Standalone Mode</p>
              Tickety manages tickets entirely on its own — no external ITSM needed. The AI pipeline, SLA tracking, categories, comments, and all intelligence features work out of the box.
            </div>
          )}

          {itProvider === "none" && (
            <div className="text-sm text-ink-500 bg-linen-200 rounded p-4 border border-linen-300">
              <p className="font-medium text-ink-600 mb-1">Disabled</p>
              External sync is disabled. You can still create tickets manually.
            </div>
          )}
        </SettingsSection>

        {/* ═══ SLA Targets ═══ */}
        <SettingsSection title="SLA Targets" subtitle="Set resolution time targets per priority level. Used by SLA clocks and escalation risk scoring.">
          <div className="grid grid-cols-3 gap-4">
            {[["SLA_P1_HOURS", "P1 (Critical)", "4"], ["SLA_P2_HOURS", "P2 (High)", "24"], ["SLA_P3_HOURS", "P3 (Normal)", "72"]].map(([key, label, def]) => (
              <label key={key} className="block space-y-1.5">
                <span className="text-sm font-medium text-ink-600">{label}</span>
                <div className="flex items-center gap-2">
                  <input type="number" min={1} max={720} value={(form[key as keyof SettingsType] as string) || def} onChange={(e) => handleChange(key as keyof SettingsType, e.target.value)} placeholder={def} className="input-base" />
                  <span className="text-xs text-ink-400 shrink-0">hrs</span>
                </div>
              </label>
            ))}
          </div>
          <p className="text-xs text-ink-400">
            Tickets past their SLA window automatically get +15 escalation risk. At half their SLA they get +8.
          </p>
        </SettingsSection>

        {/* ═══ External OAuth + Agent Sync (conditional) ═══ */}
        {itProvider === "external" && (
          <>
            <OAuthSection form={form} onChange={handleChange} />
            <AgentSection />
          </>
        )}

        {/* ═══ Category Management ═══ */}
        <CategorySection />

        {/* ═══ Organization / Branding ═══ */}
        <SettingsSection title="Organization" subtitle="Customize the workspace name and branding shown across Tickety">
          <Field label="Organization Name">
            <input type="text" value={form.ORG_NAME || ""} onChange={(e) => handleChange("ORG_NAME", e.target.value)} placeholder="Acme IT Support" className="input-base" />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Logo URL">
              <input type="text" value={form.ORG_LOGO_URL || ""} onChange={(e) => handleChange("ORG_LOGO_URL", e.target.value)} placeholder="https://…" className="input-base" />
            </Field>
            <Field label="Primary Color">
              <input type="text" value={form.ORG_PRIMARY_COLOR || ""} onChange={(e) => handleChange("ORG_PRIMARY_COLOR", e.target.value)} placeholder="#6B8E5A" className="input-base" />
            </Field>
          </div>
        </SettingsSection>

        {/* ═══ AI Automation Toggles ═══ */}
        <SettingsSection title="AI Automation" subtitle="Toggle which ambient AI agents run automatically on incoming tickets">
          <div className="space-y-2">
            {[
              { key: "AUTO_TRIAGE_ENABLED", label: "Auto-Triage", desc: "Sentiment, category, priority, mood, complexity analysis on every new ticket" },
              { key: "AUTO_SUMMARIZE_ENABLED", label: "Auto-Summarization", desc: "Generate 2-3 sentence case summaries for support managers" },
              { key: "AUTO_ROUTE_ENABLED", label: "Auto-Routing", desc: "Recommend the best engineer based on skills, tier, and workload" },
              { key: "AUTO_RESOLVE_ENABLED", label: "Auto-Resolution", desc: "Generate step-by-step resolution plans with root-cause hypothesis" },
              { key: "AUTO_SYSTEMIC_ENABLED", label: "Systemic Issue Detection", desc: "Cluster similar tickets to surface broad business-impact patterns" },
            ].map((t) => (
              <ToggleRow
                key={t.key}
                label={t.label}
                desc={t.desc}
                value={(form[t.key as keyof SettingsType] as string) !== "false"}
                onChange={(v) => handleChange(t.key as keyof SettingsType, v ? "true" : "false")}
              />
            ))}
          </div>
        </SettingsSection>

        {/* ═══ Custom Statuses ═══ */}
        <StatusConfigSection />

        {/* ═══ Custom Priorities ═══ */}
        <PriorityConfigSection />

        {/* ═══ Notifications ═══ */}
        <NotificationSection />

        {/* ═══ System Maintenance ═══ */}
        <SettingsSection title="System Maintenance" subtitle="Run AI pipeline sweeps and repair data gaps across all tickets">
          <div className="space-y-3">
            <MaintenanceButton
              label="Repair AI Gaps"
              description="Fill missing summaries and resolution plans for tickets that have triage data but incomplete AI pipeline."
              icon={Zap}
              mutation={repairMut}
              loadingText="Repairing…"
              resultFormatter={(r: any) => `Filled ${r.summaries_filled} summaries, ${r.resolutions_filled} resolutions`}
            />
            <MaintenanceButton
              label="Triage All Untriaged"
              description="Run AI triage on every ticket that hasn't been analyzed yet."
              icon={Activity}
              mutation={triageAllMut}
              loadingText="Triaging…"
              resultFormatter={(r: any) => `Found ${r.found} untriaged, processed ${r.processed}`}
            />
          </div>
        </SettingsSection>

        {/* ═══ System Info ═══ */}
        <SystemInfoSection version={version} syncStatus={syncStatus} />

        {/* ═══ Save Bar ═══ */}
        <div className="sticky bottom-4 flex items-center justify-end gap-3 bg-linen-50/90 backdrop-blur rounded-lg border border-linen-400 px-4 py-3 shadow-sm">
          {saved && (
            <span className="flex items-center gap-1.5 text-sm text-ink-600">
              <CheckCircle2 className="w-4 h-4" /> Saved
            </span>
          )}
          {mutation.isError && (
            <span className="flex items-center gap-1.5 text-sm text-rust-500">
              <AlertCircle className="w-4 h-4" /> Failed to save
            </span>
          )}
          <button type="submit" disabled={mutation.isPending} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-ink-700 text-white text-sm font-semibold hover:bg-ink-800 disabled:opacity-50 transition-colors">
            {mutation.isPending ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save Changes
          </button>
        </div>
      </form>
    </div>
  );
}

// ═══ Reusable Section Wrapper ════════════════════════════════

function SettingsSection({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="card-surface p-6 space-y-4">
      <div>
        <h2 className="text-base font-semibold text-ink-700">{title}</h2>
        {subtitle && <p className="text-xs text-ink-500 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

// ═══ Field ═══════════════════════════════════════════════════

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-ink-600">{label}</span>
      {children}
    </label>
  );
}

// ═══ Secret Input ═════════════════════════════════════════════

function SecretInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [reveal, setReveal] = useState(false);
  const isMasked = value.includes("****");
  return (
    <div className="flex gap-2">
      <input
        type={reveal ? "text" : "password"}
        value={isMasked ? "" : value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={isMasked ? "•••• stored, type to replace" : placeholder}
        onFocus={() => { if (isMasked) onChange(""); }}
        className="input-base flex-1"
      />
      <button type="button" onClick={() => setReveal((r) => !r)} className="px-3 rounded-lg border border-linen-400 text-xs text-ink-500 hover:bg-linen-200">
        {reveal ? "Hide" : "Show"}
      </button>
    </div>
  );
}

// ═══ Maintenance Button ══════════════════════════════════════

function MaintenanceButton({ label, description, icon: Icon, mutation, loadingText, resultFormatter }: {
  label: string; description: string; icon: React.ComponentType<{ className?: string }>;
  mutation: any; loadingText: string; resultFormatter: (r: any) => string;
}) {
  return (
    <div className="flex items-center justify-between rounded border border-linen-400 p-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink-600 flex items-center gap-2"><Icon className="w-3.5 h-3.5 text-ink-400" /> {label}</p>
        <p className="text-xs text-ink-500 mt-0.5">{description}</p>
        {mutation.isSuccess && mutation.data && (
          <p className="text-xs text-ink-600 mt-1.5 font-medium">{resultFormatter(mutation.data)}</p>
        )}
        {mutation.isError && (
          <p className="text-xs text-rust-500 mt-1.5">Failed: {mutation.error instanceof Error ? mutation.error.message : "Unknown error"}</p>
        )}
      </div>
      <button type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending} className="shrink-0 ml-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-linen-400 text-xs font-medium text-ink-600 hover:bg-linen-200 disabled:opacity-50">
        {mutation.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
        {mutation.isPending ? loadingText : "Run"}
      </button>
    </div>
  );
}

// ═══ Category Management Section ════════════════════════════

function CategorySection() {
  const queryClient = useQueryClient();
  const { data: categories, isLoading } = useQuery({ queryKey: ["categories"], queryFn: api.getCategories });
  const [showForm, setShowForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newColor, setNewColor] = useState("slate");

  const createMut = useMutation({
    mutationFn: () => api.createCategory(newName, newDesc, newColor),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      setNewName(""); setNewDesc(""); setNewColor("slate"); setShowForm(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => fetch(`/api/categories/${id}`, { method: "DELETE" }).then(r => r.json()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
  });

  return (
    <SettingsSection title="Ticket Categories" subtitle="Manage the categories available for ticket classification">
      {isLoading ? (
        <div className="space-y-2">{[1, 2, 3].map(i => <div key={i} className="skeleton h-10 w-full" />)}</div>
      ) : (
        <div className="space-y-2">
          {(categories || []).map((cat) => (
            <div key={cat.id} className="flex items-center justify-between rounded border border-linen-400 px-3 py-2">
              <div className="flex items-center gap-3 min-w-0">
                <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", CATEGORY_COLORS.find(c => c.value === cat.color)?.className || "bg-linen-500")} />
                <div className="min-w-0">
                  <span className="text-sm font-medium text-ink-700">{cat.name}</span>
                  {cat.description && <span className="text-xs text-ink-400 ml-2">{cat.description}</span>}
                </div>
              </div>
              <button type="button" onClick={() => deleteMut.mutate(cat.id)} className="shrink-0 p-1.5 rounded text-ink-400 hover:text-rust-500 hover:bg-rust-400/10">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}

          {showForm ? (
            <div className="rounded border border-linen-400 p-4 space-y-3 bg-linen-200">
              <input type="text" placeholder="Category name" value={newName} onChange={(e) => setNewName(e.target.value)} className="input-base" />
              <input type="text" placeholder="Description (optional)" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} className="input-base" />
              <div className="flex items-center gap-2">
                <span className="text-xs text-ink-500">Color:</span>
                {CATEGORY_COLORS.map(c => (
                  <button key={c.value} type="button" onClick={() => setNewColor(c.value)} className={cn("w-5 h-5 rounded-full border-2", c.className, newColor === c.value ? "border-ink-700" : "border-transparent")} title={c.label} />
                ))}
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => createMut.mutate()} disabled={!newName.trim() || createMut.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-ink-700 text-white text-xs font-medium hover:bg-ink-800 disabled:opacity-50">
                  {createMut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                  Create
                </button>
                <button type="button" onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded text-xs text-ink-500 hover:bg-linen-300">Cancel</button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setShowForm(true)} className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-600 hover:text-ink-700">
              <Plus className="w-3.5 h-3.5" /> Add Category
            </button>
          )}
        </div>
      )}
    </SettingsSection>
  );
}

// ═══ System Info Section ═════════════════════════════════════

function SystemInfoSection({ version, syncStatus }: { version?: BuildInfo; syncStatus?: any }) {
  return (
    <SettingsSection title="System Information" subtitle="Build version, sync status, and runtime details">
      <div className="grid grid-cols-2 gap-4">
        <InfoTile label="Version" value={version?.version || "—"} />
        <InfoTile label="Build SHA" value={version?.build_sha || "—"} mono />
        <InfoTile label="Build Time" value={version?.build_time || "—"} mono />
        <InfoTile label="Sync Status" value={syncStatus?.last_status || "idle"} />
        {syncStatus?.last_synced_at && <InfoTile label="Last Sync" value={syncStatus.last_synced_at} />}
        {syncStatus?.total_synced !== undefined && <InfoTile label="Total Synced" value={String(syncStatus.total_synced)} />}
        {syncStatus?.provider && <InfoTile label="Provider" value={syncStatus.provider} />}
      </div>
    </SettingsSection>
  );
}

function InfoTile({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded border border-linen-400 px-3 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">{label}</p>
      <p className={cn("text-sm text-ink-600 mt-0.5", mono && "font-mono text-xs")}>{value}</p>
    </div>
  );
}

// ═══ Agent Management Section ═══════════════════════════════

function AgentSection() {
  const queryClient = useQueryClient();
  const { data: agentList, isLoading } = useQuery({ queryKey: ["agents"], queryFn: api.getAgents });
  const syncMut = useMutation({
    mutationFn: api.syncAgents,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["me"] });
      queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
    },
  });
  const agents = agentList?.agents ?? [];

  return (
    <SettingsSection title="Agent Accounts" subtitle="Sync agents from your external ITSM provider to create Tickety accounts for point tracking">
      <div className="flex items-center justify-end">
        <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-ink-700 text-white text-sm font-medium hover:bg-ink-800 disabled:opacity-50">
          {syncMut.isPending ? <><RefreshCw className="w-4 h-4 animate-spin" /> Syncing…</> : <><Download className="w-4 h-4" /> Fetch Agents</>}
        </button>
      </div>
      {syncMut.isSuccess && syncMut.data && (
        <div className="rounded border border-linen-400 bg-linen-200 p-3 text-sm">
          <span className="font-medium text-ink-600">Sync complete:</span> {syncMut.data.result.total} fetched,{" "}
          <span className="text-ink-600 font-medium">{syncMut.data.result.created} created</span>
          {syncMut.data.result.updated > 0 && <>, <span className="text-ink-600">{syncMut.data.result.updated} updated</span></>}
          {syncMut.data.result.errors > 0 && <>, <span className="text-rust-500 font-medium">{syncMut.data.result.errors} errors</span></>}
        </div>
      )}
      {isLoading ? (
        <div className="space-y-2">{[1, 2, 3].map(i => <div key={i} className="skeleton h-10 w-full" />)}</div>
      ) : agents.length > 0 ? (
        <div className="overflow-hidden rounded border border-linen-400">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-linen-400 bg-linen-200">
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Name</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Email</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-ink-500 uppercase tracking-wider">Title</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold text-ink-500 uppercase tracking-wider">Points</th>
                <th className="px-4 py-2.5 text-center text-xs font-semibold text-ink-500 uppercase tracking-wider">Tier</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.id} className="border-b border-linen-300 last:border-0 hover:bg-linen-200">
                  <td className="px-4 py-2.5 font-medium text-ink-700">{a.name}</td>
                  <td className="px-4 py-2.5 text-ink-500">{a.email || "—"}</td>
                  <td className="px-4 py-2.5 text-ink-500">{a.title || "—"}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums font-medium text-ink-600">{a.impact_points.toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-center"><span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border border-linen-400 text-ink-600">T{a.tier}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-ink-400 py-2">Click &ldquo;Fetch Agents&rdquo; to sync agent accounts from your external provider.</p>
      )}
    </SettingsSection>
  );
}

// ═══ OAuth Section ═══════════════════════════════════════════

function OAuthSection({ form, onChange }: { form: Partial<SettingsType>; onChange: (key: keyof SettingsType, value: string) => void }) {
  const { data: status } = useQuery({ queryKey: ["oauth-status"], queryFn: api.getOAuthStatus, refetchInterval: 30000 });
  const authMut = useMutation({ mutationFn: api.getOAuthAuthorizeUrl, onSuccess: (res) => window.open(res.url, "_blank", "width=700,height=600") });

  return (
    <SettingsSection title="External OAuth 2.0" subtitle="Authenticate via OAuth. Once connected, the API key is ignored.">
      <div className="flex items-center justify-end">
        {status?.connected ? (
          <span className="inline-flex items-center gap-1.5 rounded border border-linen-400 px-3 py-1.5 text-xs font-medium text-ink-600">
            <ShieldCheck className="w-3.5 h-3.5" /> Connected to {status.domain}
          </span>
        ) : (
          <button onClick={() => authMut.mutate()} disabled={authMut.isPending} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-ink-700 text-white text-sm font-medium hover:bg-ink-800 disabled:opacity-50">
            {authMut.isPending ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
            Authorize
          </button>
        )}
      </div>
      {authMut.isError && (
        <div className="rounded border border-rust-400/30 bg-rust-400/10 p-3 text-sm text-red-700">
          {authMut.error instanceof Error ? authMut.error.message : "Failed to get authorization URL"}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="OAuth Client ID">
          <SecretInput value={form["FRESHSERVICE_OAUTH_CLIENT_ID"] || ""} onChange={(v) => onChange("FRESHSERVICE_OAUTH_CLIENT_ID", v)} placeholder="From provider developer portal" />
        </Field>
        <Field label="OAuth Client Secret">
          <SecretInput value={form["FRESHSERVICE_OAUTH_CLIENT_SECRET"] || ""} onChange={(v) => onChange("FRESHSERVICE_OAUTH_CLIENT_SECRET", v)} placeholder="Client secret" />
        </Field>
      </div>
      <Field label="Redirect URI (must match provider app config)">
        <input type="text" value={form["FRESHSERVICE_OAUTH_REDIRECT_URI"] || ""} onChange={(e) => onChange("FRESHSERVICE_OAUTH_REDIRECT_URI", e.target.value)} placeholder="http://localhost:8000/oauth/callback" className="input-base" />
      </Field>
    </SettingsSection>
  );
}

// ═══ Toggle Row (AI automation) ═══════════════════════════════

function ToggleRow({ label, desc, value, onChange }: { label: string; desc: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between rounded border border-linen-400 p-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink-600">{label}</p>
        <p className="text-xs text-ink-400 mt-0.5">{desc}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={cn(
          "relative shrink-0 w-10 h-5 rounded-full transition-colors ml-3",
          value ? "bg-moss-500" : "bg-linen-400"
        )}
      >
        <span className={cn(
          "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform",
          value ? "translate-x-5" : "translate-x-0.5"
        )} />
      </button>
    </div>
  );
}

// ═══ Custom Status Config Section ═════════════════════════════

function StatusConfigSection() {
  const queryClient = useQueryClient();
  const { data: statuses, isLoading } = useQuery({ queryKey: ["status-config"], queryFn: api.getStatusConfig });
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [color, setColor] = useState("slate");
  const [isOpen, setIsOpen] = useState(true);
  const [isTerminal, setIsTerminal] = useState(false);

  const createMut = useMutation({
    mutationFn: () => api.createStatusConfig({ name, label, color, is_open: isOpen, is_terminal: isTerminal, sort_order: (statuses?.length || 0) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["status-config"] });
      setName(""); setLabel(""); setColor("slate"); setIsOpen(true); setIsTerminal(false); setShowForm(false);
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteStatusConfig(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["status-config"] }),
  });

  return (
    <SettingsSection title="Ticket Statuses" subtitle="Configure the ticket lifecycle statuses available across the system">
      {isLoading ? (
        <div className="space-y-2">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-10 w-full" />)}</div>
      ) : (
        <div className="space-y-2">
          {(statuses || []).map((s) => (
            <div key={s.id} className="flex items-center justify-between rounded border border-linen-400 px-3 py-2">
              <div className="flex items-center gap-3">
                <span className={cn("w-2.5 h-2.5 rounded-full", `bg-${s.color === "moss" ? "moss-500" : "linen-500"}`)} />
                <div>
                  <span className="text-sm font-medium text-ink-700">{s.label}</span>
                  <span className="text-xs text-ink-400 ml-2">({s.name})</span>
                </div>
                <div className="flex gap-1.5">
                  {s.is_open && <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-400/10 text-blue-500 border border-blue-400/20">open</span>}
                  {s.is_terminal && <span className="text-[10px] px-1.5 py-0.5 rounded bg-linen-300 text-ink-500">terminal</span>}
                </div>
              </div>
              <button type="button" onClick={() => deleteMut.mutate(s.id)} className="p-1.5 rounded text-ink-400 hover:text-rust-500 hover:bg-rust-400/10">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          {showForm ? (
            <div className="rounded border border-linen-400 p-4 space-y-3 bg-linen-200">
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="Name (e.g. On Hold)" value={name} onChange={(e) => setName(e.target.value)} className="input-base" />
                <input placeholder="Label" value={label} onChange={(e) => setLabel(e.target.value)} className="input-base" />
              </div>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-xs text-ink-500">
                  <input type="checkbox" checked={isOpen} onChange={(e) => setIsOpen(e.target.checked)} /> Counts as open
                </label>
                <label className="flex items-center gap-2 text-xs text-ink-500">
                  <input type="checkbox" checked={isTerminal} onChange={(e) => setIsTerminal(e.target.checked)} /> Terminal (closed/resolved)
                </label>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => createMut.mutate()} disabled={!name.trim() || !label.trim()} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-ink-700 text-white text-xs font-medium hover:bg-ink-800 disabled:opacity-50">
                  <Plus className="w-3 h-3" /> Create
                </button>
                <button type="button" onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded text-xs text-ink-500 hover:bg-linen-300">Cancel</button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setShowForm(true)} className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-600 hover:text-ink-700">
              <Plus className="w-3.5 h-3.5" /> Add Status
            </button>
          )}
        </div>
      )}
    </SettingsSection>
  );
}

// ═══ Custom Priority Config Section ═══════════════════════════

function PriorityConfigSection() {
  const queryClient = useQueryClient();
  const { data: priorities, isLoading } = useQuery({ queryKey: ["priority-config"], queryFn: api.getPriorityConfig });
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [slaHours, setSlaHours] = useState("");
  const [weight, setWeight] = useState("10");

  const createMut = useMutation({
    mutationFn: () => api.createPriorityConfig({
      name, label, sla_hours: slaHours ? parseInt(slaHours) : null, weight: parseInt(weight) || 10,
      sort_order: priorities?.length || 0,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["priority-config"] });
      setName(""); setLabel(""); setSlaHours(""); setWeight("10"); setShowForm(false);
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deletePriorityConfig(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["priority-config"] }),
  });

  return (
    <SettingsSection title="Ticket Priorities" subtitle="Define priority levels with SLA targets and sort weights">
      {isLoading ? (
        <div className="space-y-2">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-10 w-full" />)}</div>
      ) : (
        <div className="space-y-2">
          {(priorities || []).map((p) => (
            <div key={p.id} className="flex items-center justify-between rounded border border-linen-400 px-3 py-2">
              <div className="flex items-center gap-3">
                <span className="text-sm font-bold text-ink-700">{p.name}</span>
                <span className="text-xs text-ink-500">{p.label}</span>
                {p.sla_hours && <span className="text-xs text-ink-400">SLA: {p.sla_hours}h</span>}
                <span className="text-xs text-ink-400">weight: {p.weight}</span>
              </div>
              <button type="button" onClick={() => deleteMut.mutate(p.id)} className="p-1.5 rounded text-ink-400 hover:text-rust-500 hover:bg-rust-400/10">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          {showForm ? (
            <div className="rounded border border-linen-400 p-4 space-y-3 bg-linen-200">
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="Name (e.g. P5)" value={name} onChange={(e) => setName(e.target.value)} className="input-base" />
                <input placeholder="Label (e.g. Trivial)" value={label} onChange={(e) => setLabel(e.target.value)} className="input-base" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <input type="number" placeholder="SLA hours" value={slaHours} onChange={(e) => setSlaHours(e.target.value)} className="input-base" />
                <input type="number" placeholder="Sort weight" value={weight} onChange={(e) => setWeight(e.target.value)} className="input-base" />
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => createMut.mutate()} disabled={!name.trim() || !label.trim()} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-ink-700 text-white text-xs font-medium hover:bg-ink-800 disabled:opacity-50">
                  <Plus className="w-3 h-3" /> Create
                </button>
                <button type="button" onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded text-xs text-ink-500 hover:bg-linen-300">Cancel</button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setShowForm(true)} className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-600 hover:text-ink-700">
              <Plus className="w-3.5 h-3.5" /> Add Priority
            </button>
          )}
        </div>
      )}
    </SettingsSection>
  );
}

// ═══ Notification Config Section ═════════════════════════════

function NotificationSection() {
  const queryClient = useQueryClient();
  const { data: notifs, isLoading } = useQuery({ queryKey: ["notif-config"], queryFn: api.getNotificationConfig });
  const updateMut = useMutation({
    mutationFn: ({ event, enabled, channels }: { event: string; enabled: boolean; channels: string }) =>
      api.updateNotificationConfig(event, enabled, channels),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notif-config"] }),
  });

  return (
    <SettingsSection title="Notifications" subtitle="Configure which events trigger alerts and through which channels">
      {isLoading ? (
        <div className="space-y-2">{[1, 2, 3].map((i) => <div key={i} className="skeleton h-10 w-full" />)}</div>
      ) : (
        <div className="space-y-2">
          {(notifs || []).map((n) => (
            <div key={n.event} className="flex items-center justify-between rounded border border-linen-400 p-3">
              <div>
                <p className="text-sm font-medium text-ink-600">{n.label}</p>
                <p className="text-xs text-ink-400">{n.event} · {n.channels}</p>
              </div>
              <button
                type="button"
                onClick={() => updateMut.mutate({ event: n.event, enabled: !n.enabled, channels: n.channels })}
                className={cn(
                  "relative shrink-0 w-10 h-5 rounded-full transition-colors",
                  n.enabled ? "bg-moss-500" : "bg-linen-400"
                )}
              >
                <span className={cn(
                  "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform",
                  n.enabled ? "translate-x-5" : "translate-x-0.5"
                )} />
              </button>
            </div>
          ))}
        </div>
      )}
    </SettingsSection>
  );
}