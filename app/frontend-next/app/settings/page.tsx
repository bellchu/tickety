"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Settings as SettingsType, LlmCatalog, LlmProvider, TicketCategory, BuildInfo, SyncAgentsOptions } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  Settings as SettingsIcon, Save, RefreshCw, CheckCircle2, AlertCircle,
  Users, Download, Database, Zap, Plus, Trash2, ShieldCheck, Activity,
  Power, KeyRound, Link2, SlidersHorizontal,
} from "lucide-react";
import { SearchableSelect } from "@/components/ui/SearchableSelect";
import { Alert, Button, ErrorState, Skeleton } from "@/components/ui";

const PROVIDER_OPTIONS = [
  { value: "standalone", label: "Standalone", description: "Built-in ticketing" },
  { value: "freshservice", label: "Freshservice", description: "Freshservice API" },
  { value: "jira", label: "Jira Service Management", description: "Atlassian Jira API" },
  { value: "none", label: "None", description: "Disable external sync" },
];

const PROVIDER_IDS = ["deepseek", "openai", "openrouter", "azure", "azure_ai", "custom"] as const;

const API_READ_ONLY_KEYS = new Set([
  "APP_MODE",
  "SEED_DEMO_DATA",
  "DATABASE_URL",
  "NEXT_PUBLIC_API_URL",
  "NEXT_PUBLIC_WS_URL",
  "LLM_ALLOW_PRIVATE_ENDPOINTS",
  "LLM_ALLOW_INSECURE_ENDPOINTS",
  "LLM_ALLOWED_PROVIDER_HOSTS",
]);

// Keep this list aligned with app/backend/settings.py::_PRODUCTION_ENV_ONLY_KEYS.
// Production renders these effective values for visibility, but changes must be
// made through the reviewed deployment environment/Secret rather than the DB.
const PRODUCTION_DEPLOYMENT_KEYS = new Set([
  "DEEPSEEK_API_KEY",
  "OPENAI_API_KEY",
  "OPENAI_API_BASE",
  "OPENROUTER_API_KEY",
  "OPENROUTER_API_BASE",
  "AZURE_API_KEY",
  "AZURE_API_BASE",
  "AZURE_API_VERSION",
  "AZURE_AI_API_KEY",
  "AZURE_AI_API_BASE",
  "CUSTOM_API_KEY",
  "CUSTOM_API_BASE",
  "FRESHSERVICE_API_KEY",
  "JIRA_API_TOKEN",
  "FRESHSERVICE_OAUTH_CLIENT_SECRET",
  "WEBHOOK_SECRET",
  "WEBHOOK_MAX_AGE_SECONDS",
  "SSO_CLIENT_SECRET",
  "CORS_ALLOW_ORIGINS",
  "COOKIE_SECURE",
  "COOKIE_SAMESITE",
  "LOGIN_REQUIRED",
  "DEFAULT_MODEL",
  "CUSTOM_PROVIDER_TYPE",
  "CUSTOM_API_VERSION",
  "CUSTOM_TEMPERATURE",
  "CUSTOM_MAX_TOKENS",
  "LLM_ALLOW_SYNTHETIC",
  "LLM_REQUEST_TIMEOUT_SECONDS",
  "LLM_OVERALL_TIMEOUT_SECONDS",
  "LLM_MAX_PROMPT_CHARS",
  "LLM_MAX_CONCURRENCY",
  "LLM_PERSIST_METRICS",
  "LLM_DAILY_TOKEN_BUDGET",
  "LLM_PROVIDER_REQUESTS_PER_MINUTE",
  "LLM_PROVIDER_TOKENS_PER_MINUTE",
  "LLM_ENFORCE_PROVIDER_LIMITS",
  "AI_USER_REQUESTS_PER_MINUTE",
  "AI_USER_REQUESTS_PER_DAY",
  "ANALYTICS_USER_REQUESTS_PER_MINUTE",
  "ANALYTICS_USER_REQUESTS_PER_DAY",
  "AI_INDEX_WRITES_PER_MINUTE",
  "AI_INDEX_WRITES_PER_DAY",
  "PORTAL_TICKETS_PER_MINUTE",
  "PORTAL_TICKETS_PER_DAY",
  "PORTAL_TICKETS_GLOBAL_PER_MINUTE",
  "PORTAL_TICKETS_GLOBAL_PER_DAY",
  "AI_ANALYSIS_LEASE_SECONDS",
  "AI_ANALYSIS_MAX_ATTEMPTS",
  "AI_PIPELINE_TIMEOUT_SECONDS",
  "TICKET_EMBEDDING_ENABLED",
  "TICKET_EMBEDDING_MODEL",
  "TICKET_EMBEDDING_DIMENSIONS",
  "TICKET_EMBEDDING_TIMEOUT_SECONDS",
  "TICKET_EMBEDDING_MAX_CHARS",
  "TICKET_EMBEDDING_MAX_COMMENTS_PER_REFRESH",
  "TICKET_VECTOR_MIN_SCORE",
  "TICKET_EMBEDDING_API_BASE",
  "AUTO_TRIAGE_ENABLED",
  "AUTO_SUMMARIZE_ENABLED",
  "AUTO_ROUTE_ENABLED",
  "AUTO_RESOLVE_ENABLED",
  "AUTO_SYSTEMIC_ENABLED",
  "ITSM_PROVIDER",
  "FRESHSERVICE_DOMAIN",
  "FRESHWORKS_ORG_DOMAIN",
  "FRESHSERVICE_WORKSPACE_ID",
  "FRESHSERVICE_TICKET_INCLUDES",
  "FRESHSERVICE_AGENT_STATE",
  "FRESHSERVICE_OAUTH_CLIENT_ID",
  "FRESHSERVICE_OAUTH_REDIRECT_URI",
  "FRESHSERVICE_OAUTH_SCOPES",
  "JIRA_BASE_URL",
  "JIRA_EMAIL",
  "JIRA_PROJECT_KEY",
  "JIRA_ISSUE_TYPE",
  "SYNC_INTERVAL_SECONDS",
  "SSO_ENABLED",
  "SSO_PROVIDER",
  "SSO_CLIENT_ID",
  "SSO_DISCOVERY_URL",
  "SSO_REDIRECT_URI",
  "SSO_ALLOWED_DOMAINS",
  "SSO_AUTO_PROVISION",
]);

type FreshserviceAuthMode = "api" | "oauth";
type AgentSyncMode = "sync" | "merge";

const FRESHSERVICE_DEFAULT_SCOPES = "freshservice.tickets.view freshservice.tickets.edit freshservice.agents.manage";

function normalizeDomain(value: string) {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  try {
    const parsed = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    return parsed.host || trimmed;
  } catch {
    return trimmed.replace(/^https?:\/\//, "");
  }
}

function ensureHttpsUrl(value: string) {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  return trimmed.includes("://") ? trimmed : `https://${trimmed}`;
}

function isAuthError(error: unknown) {
  return error instanceof Error && error.message.toLowerCase().includes("not authenticated");
}

const CATEGORY_COLORS = [
  { value: "slate", label: "Slate", className: "bg-linen-500" },
  { value: "blue", label: "Blue", className: "bg-blue-400" },
  { value: "emerald", label: "Emerald", className: "bg-emerald-400" },
  { value: "amber", label: "Amber", className: "bg-amber-400" },
  { value: "violet", label: "Violet", className: "bg-violet-400" },
  { value: "cyan", label: "Cyan", className: "bg-cyan-400" },
  { value: "red", label: "Red", className: "bg-rust-400" },
];

async function postMaintenanceAction(path: string) {
  const res = await fetch(path, { method: "POST", credentials: "include", cache: "no-store" });
  const text = await res.text();
  let data: Record<string, unknown> = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!res.ok) throw new Error(`Maintenance request failed with HTTP ${res.status}`);
      throw new Error("Maintenance request returned an invalid response");
    }
  }
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return data;
}

export default function SettingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const catalogQuery = useQuery({ queryKey: ["llm-catalog"], queryFn: api.getLlmCatalog });
  const { data, isLoading, error: settingsError } = settingsQuery;
  const { data: catalog, error: catalogError } = catalogQuery;
  const { data: version } = useQuery({ queryKey: ["version"], queryFn: api.getVersion, staleTime: Infinity });
  const { data: syncStatus } = useQuery({ queryKey: ["sync-status"], queryFn: api.getSyncStatus, refetchInterval: 30000 });

  const [form, setForm] = useState<Partial<SettingsType>>({});
  const [saved, setSaved] = useState(false);
  const [freshserviceAuthMode, setFreshserviceAuthMode] = useState<FreshserviceAuthMode>("api");
  const appMode = ((form.APP_MODE || data?.APP_MODE) as string) || "demo";
  const productionSettingsReadOnly = appMode === "production";
  const isDeploymentManaged = (key: string) => productionSettingsReadOnly && PRODUCTION_DEPLOYMENT_KEYS.has(key);

  useEffect(() => {
    if (data) {
      setForm({
        ...data,
        ITSM_PROVIDER: data.ITSM_PROVIDER === "external" ? "freshservice" : data.ITSM_PROVIDER,
      });
      const hasOAuthApp = data.FRESHSERVICE_OAUTH_CLIENT_ID__set || data.FRESHSERVICE_OAUTH_CLIENT_SECRET__set;
      if (data.FRESHSERVICE_OAUTH_ACCESS_TOKEN__set || (!data.FRESHSERVICE_API_KEY__set && hasOAuthApp)) {
        setFreshserviceAuthMode("oauth");
      }
    }
  }, [data]);

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

  const authError = isAuthError(settingsError) || isAuthError(catalogError) || isAuthError(mutation.error);

  useEffect(() => {
    if (authError) {
      router.replace("/login?next=/settings");
    }
  }, [authError, router]);

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
    mutationFn: () => postMaintenanceAction("/api/admin/sync/repair"),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["tickets"] }); },
  });

  const triageAllMut = useMutation({
    mutationFn: () => postMaintenanceAction("/api/admin/sync/triage-all"),
  });

  const handleChange = (key: keyof SettingsType, value: string) => {
    if (isDeploymentManaged(String(key))) return;
    if (mutation.isError) mutation.reset();
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const activeProviderId = useMemo(() => {
    if (!catalog) return "deepseek";
    const model = (form.DEFAULT_MODEL || "").trim();
    if (model.startsWith("openrouter/")) return "openrouter";
    if (model.startsWith("azure_ai/")) return "azure_ai";
    if (model.startsWith("azure/")) return "azure";
    if (model.startsWith("openai/")) return "openai";
    if (model.startsWith("custom/")) return "custom";
    if (model.startsWith("deepseek")) return "deepseek";
    return (catalog.current_provider as string) || "deepseek";
  }, [form.DEFAULT_MODEL, catalog]);

  const activeProvider: LlmProvider | undefined = catalog ? (catalog[activeProviderId] as LlmProvider) : undefined;
  const itProvider = form.ITSM_PROVIDER || "standalone";
  const automationValue = (key: string) => {
    const value = form[key as keyof SettingsType] as string | undefined;
    if (value === "true") return true;
    if (value === "false") return false;
    return appMode !== "production";
  };
  const keyReady = (key: string) => {
    const setFlag = data?.[`${key}__set`];
    if (typeof setFlag === "boolean") return setFlag;
    const value = form[key as keyof SettingsType];
    return typeof value === "string" && value.trim() !== "" && !value.includes("****");
  };
  const freshserviceAuthReady = freshserviceAuthMode === "oauth"
    ? keyReady("FRESHSERVICE_OAUTH_ACCESS_TOKEN")
    : keyReady("FRESHSERVICE_API_KEY");
  const freshserviceReady = Boolean(
    form.FRESHSERVICE_DOMAIN?.trim() &&
    freshserviceAuthReady
  );
  const jiraReady = Boolean(
    form.JIRA_BASE_URL?.trim() &&
    form.JIRA_EMAIL?.trim() &&
    form.JIRA_PROJECT_KEY?.trim() &&
    keyReady("JIRA_API_TOKEN")
  );
  const isExternalProvider = itProvider === "freshservice" || itProvider === "jira";
  const baselineForm = useMemo(() => data ? {
    ...data,
    ITSM_PROVIDER: data.ITSM_PROVIDER === "external" ? "freshservice" : data.ITSM_PROVIDER,
  } : null, [data]);
  const isDirty = baselineForm ? JSON.stringify(form) !== JSON.stringify(baselineForm) : false;

  const handleProviderChange = (pid: string) => {
    const prov = catalog ? (catalog[pid] as LlmProvider) : undefined;
    if (!prov) return;
    const firstModel = prov.models[0]?.id || (prov.model_hint ? prov.model_hint : "");
    handleChange("DEFAULT_MODEL", firstModel);
  };

  const handleItsmProviderChange = (provider: string) => {
    setForm((prev) => {
      const next = { ...prev, ITSM_PROVIDER: provider };
      if (provider === "freshservice") {
        next.SYNC_INTERVAL_SECONDS = next.SYNC_INTERVAL_SECONDS || "60";
        next.FRESHSERVICE_TICKET_INCLUDES = next.FRESHSERVICE_TICKET_INCLUDES || "stats,requester";
        next.FRESHSERVICE_OAUTH_SCOPES = next.FRESHSERVICE_OAUTH_SCOPES || FRESHSERVICE_DEFAULT_SCOPES;
        if (!next.FRESHWORKS_ORG_DOMAIN && next.FRESHSERVICE_DOMAIN) {
          next.FRESHWORKS_ORG_DOMAIN = next.FRESHSERVICE_DOMAIN;
        }
      }
      if (provider === "jira") {
        next.SYNC_INTERVAL_SECONDS = next.SYNC_INTERVAL_SECONDS || "60";
        next.JIRA_ISSUE_TYPE = next.JIRA_ISSUE_TYPE || "Task";
      }
      return next;
    });
  };

  const normalizeFreshserviceDomain = () => {
    setForm((prev) => {
      const domain = normalizeDomain(prev.FRESHSERVICE_DOMAIN || "");
      const orgDomain = prev.FRESHWORKS_ORG_DOMAIN || domain;
      return { ...prev, FRESHSERVICE_DOMAIN: domain, FRESHWORKS_ORG_DOMAIN: orgDomain };
    });
  };

  const normalizeJiraUrl = () => {
    setForm((prev) => ({ ...prev, JIRA_BASE_URL: ensureHttpsUrl(prev.JIRA_BASE_URL || "") }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (authError) {
      router.replace("/login?next=/settings");
      return;
    }
    const payload: Record<string, string> = {};
    for (const key of Object.keys(form)) {
      const v = form[key as keyof SettingsType];
      if (typeof v !== "string" || v === "") continue;
      if (v.includes("****")) continue;
      if (API_READ_ONLY_KEYS.has(key)) continue;
      if (isDeploymentManaged(key)) continue;
      payload[key] = v;
    }
    mutation.mutate(payload);
  };

  if (isLoading) {
    return (
      <div className="space-y-5" aria-busy="true" aria-label="Loading administration settings">
        <Skeleton className="h-12 w-72" />
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (authError) {
    return (
      <div className="flex items-center justify-center py-20 text-ink-400">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Opening sign in…
      </div>
    );
  }

  if (settingsError) {
    return (
      <ErrorState
        title="Settings could not be loaded"
        description="Administration controls are unavailable, so no configuration values are being shown or changed."
        actionLabel="Retry settings"
        onRetry={() => void settingsQuery.refetch()}
        retrying={settingsQuery.isFetching}
      />
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      {/* Header */}
      <header className="flex items-start gap-4 border-b border-linen-300 pb-6">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-semantic-primary">
          <SettingsIcon className="h-5 w-5" aria-hidden="true" />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-semantic-primary">Administration</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-[-0.03em] text-ink-700">System settings</h1>
          <p className="mt-2 text-sm leading-6 text-ink-500">Configure intelligence, ticketing, security, workflow, and operational maintenance.</p>
        </div>
      </header>

      {catalogError && !isAuthError(catalogError) && (
        <Alert variant="warning" title="Model catalog unavailable" action={<Button variant="secondary" size="sm" onClick={() => void catalogQuery.refetch()} pending={catalogQuery.isFetching} pendingLabel="Retrying…">Retry</Button>}>
          Saved settings are available, but provider and model choices may be incomplete until the catalog reconnects.
        </Alert>
      )}

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* ═══ LLM Configuration ═══ */}
        <SettingsSection title="LLM Configuration" subtitle="Choose the AI provider and model for ticket triage, summarization, and resolution">
          {productionSettingsReadOnly && (
            <DeploymentManagedNotice>
              Provider selection, model routing, endpoints, and credentials are read-only here. Update the deployment environment/Secret and roll out the workloads to change them.
            </DeploymentManagedNotice>
          )}
          <Field label="Provider">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {PROVIDER_IDS.map((pid) => {
                const provider = catalog ? (catalog[pid] as LlmProvider | undefined) : undefined;
                const selected = activeProviderId === pid;
                const requiredKeys = provider?.env_keys.filter((ek) => !ek.placeholder.toLowerCase().includes("optional")) ?? [];
                const ready = Boolean(provider && requiredKeys.every((ek) => keyReady(ek.key)));
                return (
                  <button
                    key={pid}
                    type="button"
                    onClick={() => handleProviderChange(pid)}
                    disabled={productionSettingsReadOnly}
                    className={cn(
                      "min-h-[68px] rounded border px-3 py-2 text-left transition-colors",
                      productionSettingsReadOnly && "cursor-not-allowed opacity-70",
                      selected
                        ? "border-clay-500 bg-clay-50 text-clay-700"
                        : "border-linen-400 bg-linen-50 text-ink-600 hover:bg-linen-200"
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold">{provider?.label ?? pid}</span>
                      {selected ? <ActivePill /> : ready ? <ReadyPill /> : <OffPill />}
                    </span>
                    <span className="mt-1 flex items-center gap-1.5 text-xs text-ink-400">
                      <Power className="w-3 h-3" />
                      {selected ? "On" : ready ? "Ready to switch on" : "Needs setup"}
                    </span>
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label={<DeploymentManagedLabel label="Default Model" managed={productionSettingsReadOnly} />}>
            {activeProvider && activeProvider.models && activeProvider.models.length > 0 ? (
              <fieldset disabled={productionSettingsReadOnly} className="contents">
                <SearchableSelect
                  value={form.DEFAULT_MODEL || ""}
                  options={activeProvider.models}
                  onChange={(v) => handleChange("DEFAULT_MODEL", v)}
                  placeholder={activeProvider.model_hint || "Select or search for a model…"}
                  disabled={productionSettingsReadOnly}
                />
              </fieldset>
            ) : (
              <input type="text" value={form.DEFAULT_MODEL || ""} onChange={(e) => handleChange("DEFAULT_MODEL", e.target.value)} placeholder={activeProvider?.model_hint || "model id"} className="input-base" disabled={productionSettingsReadOnly} />
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
            <Field key={ek.key} label={<DeploymentManagedLabel label={ek.label} managed={productionSettingsReadOnly} />} ready={keyReady(ek.key)}>
              {ek.secret ? (
                <SecretInput value={(form[ek.key as keyof SettingsType] as string) || ""} onChange={(v) => handleChange(ek.key as keyof SettingsType, v)} placeholder={ek.placeholder} disabled={productionSettingsReadOnly} />
              ) : (
                <input type="text" value={(form[ek.key as keyof SettingsType] as string) || ""} onChange={(e) => handleChange(ek.key as keyof SettingsType, e.target.value)} placeholder={ek.placeholder} className="input-base" disabled={productionSettingsReadOnly} />
              )}
            </Field>
          ))}
        </SettingsSection>

        {/* ═══ Ticketing Mode ═══ */}
        <SettingsSection title="Ticketing Mode" subtitle="Choose whether Tickety uses its own built-in ticketing system or connects to an external ITSM provider">
          <Field label="Provider">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {PROVIDER_OPTIONS.map((provider) => {
                const selected = itProvider === provider.value;
                const ready =
                  provider.value === "freshservice" ? freshserviceReady :
                  provider.value === "jira" ? jiraReady :
                  true;
                return (
                  <button
                    key={provider.value}
                    type="button"
                    onClick={() => handleItsmProviderChange(provider.value)}
                    className={cn(
                      "min-h-[64px] rounded border px-3 py-2 text-left transition-colors",
                      selected
                        ? "border-clay-500 bg-clay-50 text-clay-700"
                        : "border-linen-400 bg-linen-50 text-ink-600 hover:bg-linen-200"
                      )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold">{provider.label}</span>
                      {selected ? <ActivePill /> : ready ? <ReadyPill /> : <OffPill />}
                    </span>
                    <span className="block text-xs text-ink-400 mt-0.5">{provider.description}</span>
                  </button>
                );
              })}
            </div>
          </Field>

          {itProvider === "freshservice" && (
            <ConnectionPanel
              title="Connect Freshservice"
              description="Use a Freshservice domain plus one authentication method. Tickety fills sync defaults for you."
              ready={freshserviceReady}
              steps={[
                { label: "Provider", done: true },
                { label: "Domain", done: Boolean(form.FRESHSERVICE_DOMAIN?.trim()) },
                { label: freshserviceAuthMode === "oauth" ? "OAuth token" : "API key", done: freshserviceAuthReady },
              ]}
            >
              <Field label="Freshservice Domain" ready={Boolean(form.FRESHSERVICE_DOMAIN?.trim())}>
                <input
                  type="text"
                  value={form.FRESHSERVICE_DOMAIN || ""}
                  onChange={(e) => handleChange("FRESHSERVICE_DOMAIN", e.target.value)}
                  onBlur={normalizeFreshserviceDomain}
                  placeholder="acme.freshservice.com"
                  className="input-base"
                />
              </Field>

              <div className="space-y-2">
                <span className="text-sm font-medium text-ink-600">Authentication</span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <AuthChoice
                    active={freshserviceAuthMode === "api"}
                    icon={KeyRound}
                    title="API Key"
                    description="Fastest setup"
                    onClick={() => setFreshserviceAuthMode("api")}
                  />
                  <AuthChoice
                    active={freshserviceAuthMode === "oauth"}
                    icon={ShieldCheck}
                    title="OAuth"
                    description="Use a Freshworks app"
                    onClick={() => setFreshserviceAuthMode("oauth")}
                  />
                </div>
              </div>

              {freshserviceAuthMode === "api" ? (
                <Field label={<DeploymentManagedLabel label="Freshservice API Key" managed={productionSettingsReadOnly} />} ready={keyReady("FRESHSERVICE_API_KEY")}>
                  <SecretInput value={form.FRESHSERVICE_API_KEY || ""} onChange={(v) => handleChange("FRESHSERVICE_API_KEY", v)} placeholder="Paste API key" disabled={productionSettingsReadOnly} />
                </Field>
              ) : (
                <FreshserviceOAuthSetup form={form} onChange={handleChange} keyReady={keyReady} productionSettingsReadOnly={productionSettingsReadOnly} />
              )}

              <AdvancedPanel title="Advanced Freshservice Sync">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Field label="Freshworks Org Domain" ready={Boolean(form.FRESHWORKS_ORG_DOMAIN?.trim())}>
                    <input type="text" value={form.FRESHWORKS_ORG_DOMAIN || ""} onChange={(e) => handleChange("FRESHWORKS_ORG_DOMAIN", e.target.value)} onBlur={() => handleChange("FRESHWORKS_ORG_DOMAIN", normalizeDomain(form.FRESHWORKS_ORG_DOMAIN || ""))} placeholder="acme.myfreshworks.com" className="input-base" />
                  </Field>
                  <Field label="Workspace ID" ready={Boolean(form.FRESHSERVICE_WORKSPACE_ID?.trim())}>
                    <input type="text" value={form.FRESHSERVICE_WORKSPACE_ID || ""} onChange={(e) => handleChange("FRESHSERVICE_WORKSPACE_ID", e.target.value)} placeholder="Blank for primary, 0 for all" className="input-base" />
                  </Field>
                  <Field label="Ticket Includes" ready={Boolean(form.FRESHSERVICE_TICKET_INCLUDES?.trim())}>
                    <input type="text" value={form.FRESHSERVICE_TICKET_INCLUDES || ""} onChange={(e) => handleChange("FRESHSERVICE_TICKET_INCLUDES", e.target.value)} placeholder="stats,requester" className="input-base" />
                  </Field>
                  <Field label="Agent State" ready={Boolean(form.FRESHSERVICE_AGENT_STATE?.trim())}>
                    <select value={form.FRESHSERVICE_AGENT_STATE || ""} onChange={(e) => handleChange("FRESHSERVICE_AGENT_STATE", e.target.value)} className="input-base">
                      <option value="">Any active agent</option>
                      <option value="fulltime">Full-time</option>
                      <option value="occasional">Occasional</option>
                    </select>
                  </Field>
                  <Field label={<DeploymentManagedLabel label="Webhook Secret" managed={productionSettingsReadOnly} />} ready={keyReady("WEBHOOK_SECRET")}>
                    <SecretInput value={form.WEBHOOK_SECRET || ""} onChange={(v) => handleChange("WEBHOOK_SECRET", v)} placeholder="Shared secret" disabled={productionSettingsReadOnly} />
                  </Field>
                  <Field label="Sync Interval" ready={Boolean(form.SYNC_INTERVAL_SECONDS?.trim())}>
                    <input type="number" min={10} value={form.SYNC_INTERVAL_SECONDS || ""} onChange={(e) => handleChange("SYNC_INTERVAL_SECONDS", e.target.value)} placeholder="60" className="input-base" />
                  </Field>
                </div>
              </AdvancedPanel>
            </ConnectionPanel>
          )}

          {itProvider === "jira" && (
            <ConnectionPanel
              title="Connect Jira Service Management"
              description="Add your Atlassian site, service project, and API token. Defaults cover the rest."
              ready={jiraReady}
              steps={[
                { label: "Site", done: Boolean(form.JIRA_BASE_URL?.trim()) },
                { label: "Account", done: Boolean(form.JIRA_EMAIL?.trim()) },
                { label: "Project", done: Boolean(form.JIRA_PROJECT_KEY?.trim()) },
                { label: "Token", done: keyReady("JIRA_API_TOKEN") },
              ]}
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Jira Site URL" ready={Boolean(form.JIRA_BASE_URL?.trim())}>
                  <input type="text" value={form.JIRA_BASE_URL || ""} onChange={(e) => handleChange("JIRA_BASE_URL", e.target.value)} onBlur={normalizeJiraUrl} placeholder="https://acme.atlassian.net" className="input-base" />
                </Field>
                <Field label="Project Key" ready={Boolean(form.JIRA_PROJECT_KEY?.trim())}>
                  <input type="text" value={form.JIRA_PROJECT_KEY || ""} onChange={(e) => handleChange("JIRA_PROJECT_KEY", e.target.value.toUpperCase())} placeholder="ITSM" className="input-base" />
                </Field>
                <Field label="Atlassian Email" ready={Boolean(form.JIRA_EMAIL?.trim())}>
                  <input type="email" value={form.JIRA_EMAIL || ""} onChange={(e) => handleChange("JIRA_EMAIL", e.target.value)} placeholder="you@example.com" className="input-base" />
                </Field>
                <Field label={<DeploymentManagedLabel label="Atlassian API Token" managed={productionSettingsReadOnly} />} ready={keyReady("JIRA_API_TOKEN")}>
                  <SecretInput value={form.JIRA_API_TOKEN || ""} onChange={(v) => handleChange("JIRA_API_TOKEN", v)} placeholder="Paste API token" disabled={productionSettingsReadOnly} />
                </Field>
              </div>

              <AdvancedPanel title="Advanced Jira Sync">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Field label="Issue Type" ready={Boolean(form.JIRA_ISSUE_TYPE?.trim())}>
                    <input type="text" value={form.JIRA_ISSUE_TYPE || ""} onChange={(e) => handleChange("JIRA_ISSUE_TYPE", e.target.value)} placeholder="Task" className="input-base" />
                  </Field>
                  <Field label="Sync Interval" ready={Boolean(form.SYNC_INTERVAL_SECONDS?.trim())}>
                    <input type="number" min={10} value={form.SYNC_INTERVAL_SECONDS || ""} onChange={(e) => handleChange("SYNC_INTERVAL_SECONDS", e.target.value)} placeholder="60" className="input-base" />
                  </Field>
                </div>
              </AdvancedPanel>
            </ConnectionPanel>
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[["SLA_P1_HOURS", "P1 (Critical)", "4"], ["SLA_P2_HOURS", "P2 (High)", "24"], ["SLA_P3_HOURS", "P3 (Normal)", "72"], ["SLA_P4_HOURS", "P4 (Low)", "168"]].map(([key, label, def]) => (
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
        {isExternalProvider && <AgentSection />}

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
                value={automationValue(t.key)}
                onChange={(v) => handleChange(t.key as keyof SettingsType, v ? "true" : "false")}
              />
            ))}
          </div>
        </SettingsSection>

        {/* ═══ Security & Auth ═══ */}
        <SettingsSection title="Security & Authentication" subtitle="Require login and configure Single Sign-On (OIDC) for production deployments">
          {productionSettingsReadOnly && (
            <DeploymentManagedNotice>
              Authentication, SSO, CORS, and cookie controls are read-only here. Their effective values come from the deployment environment/Secret.
            </DeploymentManagedNotice>
          )}
          <Field label="Runtime Mode">
            <select
              value={appMode}
              disabled
              aria-describedby="runtime-mode-help"
              className="input-base"
            >
              <option value="demo">Demo</option>
              <option value="production">Production</option>
            </select>
            <span id="runtime-mode-help" className="block text-xs leading-5 text-ink-400">Runtime mode is deployment-owned and cannot be changed from the application.</span>
          </Field>
          <Field label="Frontend URL">
            <input
              type="text"
              value={form.FRONTEND_URL || ""}
              onChange={(e) => handleChange("FRONTEND_URL", e.target.value)}
              placeholder="https://support.example.com"
              className="input-base"
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label={<DeploymentManagedLabel label="CORS Allow Origins" managed={productionSettingsReadOnly} />}>
              <input
                type="text"
                value={form.CORS_ALLOW_ORIGINS || ""}
                onChange={(e) => handleChange("CORS_ALLOW_ORIGINS", e.target.value)}
                placeholder="https://support.example.com"
                className="input-base"
                disabled={productionSettingsReadOnly}
              />
            </Field>
            <Field label={<DeploymentManagedLabel label="Cookie SameSite" managed={productionSettingsReadOnly} />}>
              <select
                value={(form.COOKIE_SAMESITE as string) || "lax"}
                onChange={(e) => handleChange("COOKIE_SAMESITE", e.target.value)}
                className="input-base"
                disabled={productionSettingsReadOnly}
              >
                <option value="lax">Lax</option>
                <option value="strict">Strict</option>
                <option value="none">None</option>
              </select>
            </Field>
          </div>
          <ToggleRow
            label="Secure Cookies"
            desc="Require HTTPS for session cookies. Production mode enables this by default."
            value={(form.COOKIE_SECURE as string) === "true" || (((form.COOKIE_SECURE as string) || "") === "" && appMode === "production")}
            onChange={(v) => handleChange("COOKIE_SECURE", v ? "true" : "false")}
            disabled={productionSettingsReadOnly}
          />
          <ToggleRow
            label="Seed Demo Data"
            desc={appMode === "production" ? "Demo accounts and sample records are permanently disabled in production." : "Demo mode creates local sample users and records on startup."}
            value={appMode === "demo"}
            disabled
            onChange={() => {}}
          />
          <ToggleRow
            label="Require Login"
            desc="When enabled, users must sign in. When disabled (default), the app runs in demo mode — no login needed."
            value={(form.LOGIN_REQUIRED as string) === "true" || (((form.LOGIN_REQUIRED as string) || "") === "" && appMode === "production")}
            onChange={(v) => handleChange("LOGIN_REQUIRED", v ? "true" : "false")}
            disabled={productionSettingsReadOnly}
          />

          {appMode === "demo" && (form.LOGIN_REQUIRED as string) === "true" && (
            <div className="rounded border border-amber-400/40 bg-amber-400/5 p-3 text-xs text-ink-600">
              <p className="font-medium mb-1">Default demo accounts (seeded on first start):</p>
              <p>alice@company.com · bob@company.com · carol@company.com</p>
              <p>Password: <code className="bg-linen-200 px-1 rounded">tickety123</code></p>
            </div>
          )}

          <div className="border-t border-linen-300 my-2" />

          <ToggleRow
            label="Enable SSO (OIDC)"
            desc="Allow users to sign in via an OpenID Connect provider (Google, Azure AD, Okta, etc.)"
            value={(form.SSO_ENABLED as string) === "true"}
            onChange={(v) => handleChange("SSO_ENABLED", v ? "true" : "false")}
            disabled={productionSettingsReadOnly}
          />

          {(form.SSO_ENABLED as string) === "true" && (
            <div className="space-y-4 pt-2">
              <Field label={<DeploymentManagedLabel label="SSO Provider Name" managed={productionSettingsReadOnly} />}>
                <input type="text" value={form.SSO_PROVIDER || ""} onChange={(e) => handleChange("SSO_PROVIDER", e.target.value)} placeholder="e.g. Google, Azure AD, Okta" className="input-base" disabled={productionSettingsReadOnly} />
              </Field>
              <Field label={<DeploymentManagedLabel label="Client ID" managed={productionSettingsReadOnly} />}>
                <input type="text" value={form.SSO_CLIENT_ID || ""} onChange={(e) => handleChange("SSO_CLIENT_ID", e.target.value)} placeholder="OIDC client ID" className="input-base" disabled={productionSettingsReadOnly} />
              </Field>
              <Field label={<DeploymentManagedLabel label="Client Secret" managed={productionSettingsReadOnly} />}>
                <SecretInput value={form.SSO_CLIENT_SECRET || ""} onChange={(v) => handleChange("SSO_CLIENT_SECRET", v)} placeholder="OIDC client secret" disabled={productionSettingsReadOnly} />
              </Field>
              <Field label={<DeploymentManagedLabel label="Discovery URL" managed={productionSettingsReadOnly} />}>
                <input type="text" value={form.SSO_DISCOVERY_URL || ""} onChange={(e) => handleChange("SSO_DISCOVERY_URL", e.target.value)} placeholder="https://accounts.google.com/.well-known/openid-configuration" className="input-base" disabled={productionSettingsReadOnly} />
              </Field>
              <Field label={<DeploymentManagedLabel label="Redirect URI" managed={productionSettingsReadOnly} />}>
                <input type="text" value={form.SSO_REDIRECT_URI || ""} onChange={(e) => handleChange("SSO_REDIRECT_URI", e.target.value)} placeholder="http://localhost:3000/api/auth/sso/callback" className="input-base" disabled={productionSettingsReadOnly} />
              </Field>
              <Field label={<DeploymentManagedLabel label="Allowed Email Domains" managed={productionSettingsReadOnly} />}>
                <input type="text" value={form.SSO_ALLOWED_DOMAINS || ""} onChange={(e) => handleChange("SSO_ALLOWED_DOMAINS", e.target.value)} placeholder="company.com,subsidiary.com" className="input-base" disabled={productionSettingsReadOnly} />
              </Field>
              <ToggleRow
                label="Auto-Provision SSO Users"
                desc="Create new active agent accounts for trusted SSO domains. Keep disabled when accounts should be pre-approved."
                value={(form.SSO_AUTO_PROVISION as string) === "true"}
                onChange={(v) => handleChange("SSO_AUTO_PROVISION", v ? "true" : "false")}
                disabled={productionSettingsReadOnly}
              />
              <p className="text-xs text-ink-400">
                Use the well-known URL for your provider. Common ones:<br />
                Google: <code className="bg-linen-200 px-1">https://accounts.google.com/.well-known/openid-configuration</code><br />
                Azure AD: <code className="bg-linen-200 px-1">https://login.microsoftonline.com/&#123;tenant&#125;/v2.0/.well-known/openid-configuration</code><br />
                Okta: <code className="bg-linen-200 px-1">https://&#123;your-domain&#125;/.well-known/openid-configuration</code>
              </p>
            </div>
          )}
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
              resultFormatter={(r: any) => `Filled ${r.summaries_filled ?? 0} summaries, ${r.resolutions_filled ?? 0} resolutions`}
            />
            <MaintenanceButton
              label="Triage All Untriaged"
              description="Run AI triage on every ticket that hasn't been analyzed yet."
              icon={Activity}
              mutation={triageAllMut}
              loadingText="Triaging…"
              resultFormatter={(r: any) => `Found ${r.found ?? 0} untriaged, processed ${r.processed ?? 0}`}
            />
          </div>
        </SettingsSection>

        {/* ═══ System Info ═══ */}
        <SystemInfoSection version={version} syncStatus={syncStatus} />

        {/* ═══ Save Bar ═══ */}
        <div className="sticky bottom-4 z-30 flex flex-col gap-3 rounded-xl border border-linen-400 bg-linen-50/95 px-4 py-3 shadow-[var(--shadow-raised)] backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-ink-500">{isDirty ? "You have unsaved configuration changes." : "Configuration is up to date."}</p>
          <div className="flex items-center justify-end gap-3">
          {saved && (
            <span role="status" className="flex items-center gap-1.5 text-sm text-moss-600">
              <CheckCircle2 className="w-4 h-4" /> Saved
            </span>
          )}
          {mutation.isError && (
            <span className="flex items-center gap-1.5 text-sm text-rust-500">
              <AlertCircle className="w-4 h-4" /> {mutation.error instanceof Error ? mutation.error.message : "Failed to save"}
            </span>
          )}
          <Button type="submit" disabled={!isDirty} pending={mutation.isPending} pendingLabel="Saving…" leadingIcon={<Save className="h-4 w-4" />}>
            Save Changes
          </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

// ═══ Guided ITSM Connection ══════════════════════════════════

function ConnectionPanel({
  title,
  description,
  ready,
  steps,
  children,
}: {
  title: string;
  description: string;
  ready: boolean;
  steps: Array<{ label: string; done: boolean }>;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded border border-linen-400 bg-linen-100 p-4 space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Link2 className="w-4 h-4 text-ink-500" />
            <h3 className="text-sm font-semibold text-ink-700">{title}</h3>
          </div>
          <p className="mt-1 text-xs text-ink-500">{description}</p>
        </div>
        {ready ? <ReadyPill /> : <OffPill />}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {steps.map((step) => <SetupStep key={step.label} label={step.label} done={step.done} />)}
      </div>

      <div className="space-y-4">{children}</div>
    </div>
  );
}

function SetupStep({ label, done }: { label: string; done: boolean }) {
  return (
    <div className={cn(
      "flex items-center gap-2 rounded border px-3 py-2 text-xs font-medium",
      done ? "border-moss-500/30 bg-moss-500/10 text-moss-600" : "border-linen-400 bg-linen-50 text-ink-400"
    )}>
      {done ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0" /> : <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-linen-500" />}
      <span className="truncate">{label}</span>
    </div>
  );
}

function AuthChoice({
  active,
  icon: Icon,
  title,
  description,
  onClick,
}: {
  active: boolean;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-h-[58px] items-center gap-3 rounded border px-3 py-2 text-left transition-colors",
        active ? "border-clay-500 bg-clay-50 text-clay-700" : "border-linen-400 bg-linen-50 text-ink-600 hover:bg-linen-200"
      )}
    >
      <Icon className="w-4 h-4 shrink-0" />
      <span className="min-w-0">
        <span className="block text-sm font-semibold">{title}</span>
        <span className="block text-xs text-ink-400">{description}</span>
      </span>
    </button>
  );
}

function AdvancedPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="rounded border border-linen-400 bg-linen-50">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium text-ink-600">
        <SlidersHorizontal className="w-4 h-4" />
        {title}
      </summary>
      <div className="border-t border-linen-300 p-3">{children}</div>
    </details>
  );
}

function FreshserviceOAuthSetup({
  form,
  onChange,
  keyReady,
  productionSettingsReadOnly,
}: {
  form: Partial<SettingsType>;
  onChange: (key: keyof SettingsType, value: string) => void;
  keyReady: (key: string) => boolean;
  productionSettingsReadOnly: boolean;
}) {
  const { data: status } = useQuery({ queryKey: ["oauth-status"], queryFn: api.getOAuthStatus, refetchInterval: 30000 });
  const authMut = useMutation({ mutationFn: api.getOAuthAuthorizeUrl, onSuccess: (res) => window.open(res.url, "_blank", "width=700,height=600") });
  const configured = keyReady("FRESHSERVICE_OAUTH_CLIENT_ID") && keyReady("FRESHSERVICE_OAUTH_CLIENT_SECRET") && Boolean(form.FRESHSERVICE_OAUTH_REDIRECT_URI?.trim());

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Freshworks Org Domain" ready={Boolean(form.FRESHWORKS_ORG_DOMAIN?.trim())}>
          <input type="text" value={form.FRESHWORKS_ORG_DOMAIN || ""} onChange={(e) => onChange("FRESHWORKS_ORG_DOMAIN", e.target.value)} onBlur={() => onChange("FRESHWORKS_ORG_DOMAIN", normalizeDomain(form.FRESHWORKS_ORG_DOMAIN || ""))} placeholder="acme.myfreshworks.com" className="input-base" />
        </Field>
        <Field label="Redirect URI" ready={Boolean(form.FRESHSERVICE_OAUTH_REDIRECT_URI?.trim())}>
          <input type="text" value={form.FRESHSERVICE_OAUTH_REDIRECT_URI || ""} onChange={(e) => onChange("FRESHSERVICE_OAUTH_REDIRECT_URI", e.target.value)} placeholder="http://localhost:8000/oauth/callback" className="input-base" />
        </Field>
        <Field label="OAuth Client ID" ready={keyReady("FRESHSERVICE_OAUTH_CLIENT_ID")}>
          <SecretInput value={form.FRESHSERVICE_OAUTH_CLIENT_ID || ""} onChange={(v) => onChange("FRESHSERVICE_OAUTH_CLIENT_ID", v)} placeholder="Client ID" />
        </Field>
        <Field label={<DeploymentManagedLabel label="OAuth Client Secret" managed={productionSettingsReadOnly} />} ready={keyReady("FRESHSERVICE_OAUTH_CLIENT_SECRET")}>
          <SecretInput value={form.FRESHSERVICE_OAUTH_CLIENT_SECRET || ""} onChange={(v) => onChange("FRESHSERVICE_OAUTH_CLIENT_SECRET", v)} placeholder="Client secret" disabled={productionSettingsReadOnly} />
        </Field>
      </div>

      <Field label="OAuth Scopes" ready={Boolean(form.FRESHSERVICE_OAUTH_SCOPES?.trim())}>
        <input type="text" value={form.FRESHSERVICE_OAUTH_SCOPES || ""} onChange={(e) => onChange("FRESHSERVICE_OAUTH_SCOPES", e.target.value)} placeholder={FRESHSERVICE_DEFAULT_SCOPES} className="input-base" />
      </Field>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between rounded border border-linen-400 bg-linen-50 px-3 py-2">
        {status?.connected ? (
          <span className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-600">
            <ShieldCheck className="w-4 h-4" /> Connected to {status.domain}
          </span>
        ) : (
          <span className="text-sm text-ink-500">{configured ? "OAuth app details are ready." : "Add OAuth app details, save, then authorize."}</span>
        )}
        <button
          type="button"
          onClick={() => authMut.mutate()}
          disabled={authMut.isPending || !configured}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded bg-clay-500 text-linen-50 text-sm font-medium hover:bg-clay-600 disabled:opacity-50"
        >
          {authMut.isPending ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
          Authorize
        </button>
      </div>
      {authMut.isError && (
        <div className="rounded border border-rust-400/30 bg-rust-400/10 p-3 text-sm text-red-700">
          {authMut.error instanceof Error ? authMut.error.message : "Failed to get authorization URL"}
        </div>
      )}
    </div>
  );
}

// ═══ Reusable Section Wrapper ════════════════════════════════

function SettingsSection({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-5 rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-6">
      <div className="border-b border-linen-300 pb-4">
        <h2 className="text-lg font-semibold tracking-[-0.01em] text-ink-700">{title}</h2>
        {subtitle && <p className="mt-1 max-w-3xl text-xs leading-5 text-ink-500">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

// ═══ Field ═══════════════════════════════════════════════════

function Field({ label, children, ready }: { label: React.ReactNode; children: React.ReactNode; ready?: boolean }) {
  return (
    <label className="block space-y-1.5">
      <span className="flex items-center gap-2 text-sm font-medium text-ink-600">
        {label}
        {ready && <ReadyPill />}
      </span>
      {children}
    </label>
  );
}

function DeploymentManagedLabel({ label, managed }: { label: string; managed: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span>{label}</span>
      {managed && (
        <span className="inline-flex items-center gap-1 rounded-full border border-linen-400 bg-linen-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
          <ShieldCheck className="h-3 w-3" aria-hidden="true" /> Deployment managed
        </span>
      )}
    </span>
  );
}

function DeploymentManagedNotice({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded border border-blue-400/30 bg-blue-400/5 p-3 text-xs leading-5 text-ink-600" role="note">
      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" aria-hidden="true" />
      <p>{children}</p>
    </div>
  );
}

function ReadyPill() {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-moss-500/30 bg-moss-500/10 px-2 py-0.5 text-[11px] font-semibold text-moss-600">
      <CheckCircle2 className="w-3 h-3" /> Ready
    </span>
  );
}

function ActivePill() {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-clay-500/30 bg-clay-500/10 px-2 py-0.5 text-[11px] font-semibold text-clay-700">
      <CheckCircle2 className="w-3 h-3" /> On
    </span>
  );
}

function OffPill() {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full border border-linen-400 bg-linen-100 px-2 py-0.5 text-[11px] font-semibold text-ink-400">
      Off
    </span>
  );
}

// ═══ Secret Input ═════════════════════════════════════════════

function SecretInput({ value, onChange, placeholder, disabled = false }: { value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean }) {
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
        disabled={disabled}
      />
      <button type="button" aria-pressed={reveal} onClick={() => setReveal((r) => !r)} disabled={disabled} className="px-3 rounded-lg border border-linen-400 text-xs text-ink-500 hover:bg-linen-200 disabled:cursor-not-allowed disabled:opacity-60">
        <span className="sr-only">{reveal ? "Hide secret value" : "Show secret value"}</span>
        <span aria-hidden="true">{reveal ? "Hide" : "Show"}</span>
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
                <button type="button" onClick={() => createMut.mutate()} disabled={!newName.trim() || createMut.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-clay-500 text-linen-50 text-xs font-medium hover:bg-clay-600 disabled:opacity-50">
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
  const [syncMode, setSyncMode] = useState<AgentSyncMode>("sync");
  const [createMissing, setCreateMissing] = useState(true);
  const [updateProfiles, setUpdateProfiles] = useState(true);
  const [matchByName, setMatchByName] = useState(false);
  const [reassignTickets, setReassignTickets] = useState(true);
  const { data: agentList, isLoading } = useQuery({ queryKey: ["agents"], queryFn: api.getAgents });
  const syncOptions: SyncAgentsOptions = {
    mode: syncMode,
    create_missing: createMissing,
    merge_existing: syncMode === "merge",
    update_profiles: updateProfiles,
    match_by_name: syncMode === "merge" && matchByName,
    reassign_tickets: reassignTickets,
  };
  const syncMut = useMutation({
    mutationFn: api.syncAgents,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["me"] });
      queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
    },
  });
  const agents = agentList?.agents ?? [];
  const syncResult = syncMut.data?.result;
  const syncHadErrors = (syncResult?.errors ?? 0) > 0;
  const syncNeedsReview = Boolean(syncResult && ((syncResult.conflicts ?? 0) > 0 || (syncResult.missing ?? 0) > 0));
  const syncChangedCount = syncResult
    ? syncResult.created + syncResult.updated + syncResult.merged + syncResult.remapped + syncResult.tickets_reassigned
    : 0;
  const syncFailed = Boolean(syncResult && syncHadErrors && syncResult.total === 0 && syncChangedCount === 0);
  const syncSummary = syncResult
    ? [
        `${syncResult.total.toLocaleString()} fetched`,
        `${syncResult.created.toLocaleString()} created`,
        syncResult.merged > 0 ? `${syncResult.merged.toLocaleString()} merged` : null,
        syncResult.updated > 0 ? `${syncResult.updated.toLocaleString()} updated` : null,
        syncResult.remapped > 0 ? `${syncResult.remapped.toLocaleString()} remapped` : null,
        syncResult.missing > 0 ? `${syncResult.missing.toLocaleString()} missing` : null,
        syncResult.conflicts > 0 ? `${syncResult.conflicts.toLocaleString()} conflicts` : null,
        syncResult.skipped_inactive > 0 ? `${syncResult.skipped_inactive.toLocaleString()} inactive skipped` : null,
        syncResult.tickets_reassigned > 0 ? `${syncResult.tickets_reassigned.toLocaleString()} tickets reassigned` : null,
        syncResult.errors > 0 ? `${syncResult.errors.toLocaleString()} ${syncResult.errors === 1 ? "error" : "errors"}` : null,
      ].filter(Boolean)
    : [];

  return (
    <SettingsSection title="Agent Accounts" subtitle="Sync agents from your external ITSM provider to create Tickety accounts for point tracking">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-3 items-start">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => setSyncMode("sync")}
            className={cn(
              "min-h-[58px] rounded border px-3 py-2 text-left transition-colors",
              syncMode === "sync" ? "border-clay-500 bg-clay-50 text-clay-700" : "border-linen-400 bg-linen-50 text-ink-600 hover:bg-linen-200"
            )}
          >
            <span className="flex items-center gap-2 text-sm font-semibold"><Download className="h-4 w-4" /> Sync missing</span>
            <span className="block text-xs text-ink-400 mt-0.5">Create unmapped provider agents</span>
          </button>
          <button
            type="button"
            onClick={() => setSyncMode("merge")}
            className={cn(
              "min-h-[58px] rounded border px-3 py-2 text-left transition-colors",
              syncMode === "merge" ? "border-clay-500 bg-clay-50 text-clay-700" : "border-linen-400 bg-linen-50 text-ink-600 hover:bg-linen-200"
            )}
          >
            <span className="flex items-center gap-2 text-sm font-semibold"><Link2 className="h-4 w-4" /> Merge & reconcile</span>
            <span className="block text-xs text-ink-400 mt-0.5">Link provider agents to existing accounts</span>
          </button>
        </div>
        <button type="button" onClick={() => syncMut.mutate(syncOptions)} disabled={syncMut.isPending} className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-clay-500 text-linen-50 text-sm font-medium hover:bg-clay-600 disabled:opacity-50">
          {syncMut.isPending ? <><RefreshCw className="w-4 h-4 animate-spin" /> Syncing…</> : <><Download className="w-4 h-4" /> {syncMode === "merge" ? "Merge Agents" : "Sync Agents"}</>}
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
        <label className="flex items-start gap-2 rounded border border-linen-400 bg-linen-50 px-3 py-2 text-sm text-ink-600">
          <input type="checkbox" checked={createMissing} onChange={(e) => setCreateMissing(e.target.checked)} className="mt-0.5" />
          <span><span className="block font-medium">Create missing</span><span className="text-xs text-ink-400">Add accounts when no match exists</span></span>
        </label>
        <label className="flex items-start gap-2 rounded border border-linen-400 bg-linen-50 px-3 py-2 text-sm text-ink-600">
          <input type="checkbox" checked={updateProfiles} onChange={(e) => setUpdateProfiles(e.target.checked)} className="mt-0.5" />
          <span><span className="block font-medium">Refresh profiles</span><span className="text-xs text-ink-400">Update name, email, and title</span></span>
        </label>
        <label className={cn("flex items-start gap-2 rounded border border-linen-400 bg-linen-50 px-3 py-2 text-sm text-ink-600", syncMode !== "merge" && "opacity-60")}>
          <input type="checkbox" checked={matchByName} disabled={syncMode !== "merge"} onChange={(e) => setMatchByName(e.target.checked)} className="mt-0.5" />
          <span><span className="block font-medium">Match unique names</span><span className="text-xs text-ink-400">Use only when email is absent</span></span>
        </label>
        <label className="flex items-start gap-2 rounded border border-linen-400 bg-linen-50 px-3 py-2 text-sm text-ink-600">
          <input type="checkbox" checked={reassignTickets} onChange={(e) => setReassignTickets(e.target.checked)} className="mt-0.5" />
          <span><span className="block font-medium">Reassign tickets</span><span className="text-xs text-ink-400">Apply mapped assignees to tickets</span></span>
        </label>
      </div>
      {syncMut.isError && (
        <div className="rounded border border-rust-400 bg-linen-100 p-3 text-sm text-ink-600">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rust-500" />
            <div>
              <p className="font-medium text-rust-600">Sync failed</p>
              <p className="mt-0.5 text-ink-500">{syncMut.error instanceof Error ? syncMut.error.message : "The agent sync request could not be completed."}</p>
            </div>
          </div>
        </div>
      )}
      {syncMut.isSuccess && syncResult && (
        <div className={cn(
          "rounded border bg-linen-100 p-3 text-sm",
          syncFailed ? "border-rust-400" : syncHadErrors || syncNeedsReview ? "border-amber-400" : "border-moss-400"
        )}>
          <div className="flex items-start gap-2">
            {syncFailed || syncHadErrors || syncNeedsReview ? (
              <AlertCircle className={cn("mt-0.5 h-4 w-4 shrink-0", syncFailed ? "text-rust-500" : "text-amber-600")} />
            ) : (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-moss-600" />
            )}
            <div className="min-w-0">
              <p className={cn("font-medium", syncFailed ? "text-rust-600" : syncHadErrors || syncNeedsReview ? "text-ink-600" : "text-moss-600")}>
                {syncFailed ? "Sync failed" : syncHadErrors ? "Sync completed with errors" : syncNeedsReview ? "Sync needs review" : "Sync complete"}
              </p>
              <p className="mt-0.5 text-ink-500">{syncSummary.join(", ")}</p>
              {syncFailed && agents.length > 0 && (
                <p className="mt-1 text-xs text-ink-400">Existing accounts below are from earlier successful syncs.</p>
              )}
              {(syncResult.conflict_details?.length ?? 0) > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-amber-700">
                  {syncResult.conflict_details.slice(0, 3).map((detail, index) => (
                    <li key={`${detail}-${index}`}>{detail}</li>
                  ))}
                </ul>
              )}
              {(syncResult.missing_details?.length ?? 0) > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-ink-500">
                  {syncResult.missing_details.slice(0, 3).map((detail, index) => (
                    <li key={`${detail}-${index}`}>{detail}</li>
                  ))}
                </ul>
              )}
              {(syncResult.error_details?.length ?? 0) > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-rust-500">
                  {syncResult.error_details.slice(0, 3).map((detail, index) => (
                    <li key={`${detail}-${index}`}>{detail}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
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

// ═══ Toggle Row (AI automation) ═══════════════════════════════

function ToggleRow({ label, desc, value, onChange, disabled = false }: { label: string; desc: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <div className={cn("flex items-center justify-between rounded border border-linen-400 p-3", disabled && "opacity-65")}>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink-600">{label}</p>
        <p className="text-xs text-ink-400 mt-0.5">{desc}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!value)}
        className={cn(
          "relative shrink-0 w-10 h-5 rounded-full transition-colors ml-3 flex items-center",
          value ? "bg-moss-500 justify-end" : "bg-linen-400 justify-start"
        )}
      >
        <span className="w-4 h-4 rounded-full bg-white shadow-sm transition-all mx-0.5" />
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
                <button type="button" onClick={() => createMut.mutate()} disabled={!name.trim() || !label.trim()} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-clay-500 text-linen-50 text-xs font-medium hover:bg-clay-600 disabled:opacity-50">
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
                <button type="button" onClick={() => createMut.mutate()} disabled={!name.trim() || !label.trim()} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-clay-500 text-linen-50 text-xs font-medium hover:bg-clay-600 disabled:opacity-50">
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
                  "relative shrink-0 w-10 h-5 rounded-full transition-colors flex items-center",
                  n.enabled ? "bg-moss-500 justify-end" : "bg-linen-400 justify-start"
                )}
              >
                <span className="w-4 h-4 rounded-full bg-white shadow-sm transition-all mx-0.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </SettingsSection>
  );
}
