"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, APIError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { canAccessAdministration, isDemoAdministrationContext } from "@/lib/auth";
import {
  Settings as SettingsType,
  LlmCatalog,
  LlmProvider,
  TicketCategory,
  TicketPriorityConfig,
  TicketStatusConfig,
  BuildInfo,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  Settings as SettingsIcon, Save, RefreshCw, CheckCircle2, AlertCircle,
  Users, Download, Database, Zap, Plus, Trash2, ShieldCheck, Activity,
  Power, KeyRound, Link2, SlidersHorizontal,
  Mail, Search, ChevronLeft, ChevronRight,
} from "lucide-react";
import { SearchableSelect } from "@/components/ui/SearchableSelect";
import { Alert, Button, ConfirmDialog, DataListCard, DataTable, DataTableViewport, ErrorState, IconButton, ListText, Skeleton } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";

const PROVIDER_OPTIONS = [
  { value: "freshservice", label: "Freshservice", description: "Read-only system of record" },
];

const PROVIDER_IDS = ["foundry", "custom"] as const;

const SETTINGS_TABS = [
  { id: "overview", label: "Overview", hash: "settings-status", description: "Readiness and administration entry points" },
  { id: "ai", label: "AI", hash: "settings-ai", description: "Models and ambient automation" },
  { id: "integrations", label: "Integrations", hash: "settings-ticketing", description: "Freshservice, sync, SLA, and provider identities" },
  { id: "workspace", label: "Workspace", hash: "settings-workspace", description: "Branding and ticket taxonomy" },
  { id: "email", label: "Email", hash: "settings-email", description: "Outbound delivery and sender identity" },
  { id: "access", label: "Access", hash: "settings-access", description: "Authentication, SSO, users, and roles" },
  { id: "system", label: "System", hash: "settings-system", description: "Bounded maintenance operations" },
] as const;

type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];

const SETTINGS_TAB_HASHES: Record<string, SettingsTabId> = {
  "settings-status": "overview",
  "settings-ai": "ai",
  "settings-automation": "ai",
  "settings-ticketing": "integrations",
  "settings-directory": "integrations",
  "settings-workspace": "workspace",
  "settings-email": "email",
  "settings-access": "access",
  "settings-system": "system",
};

function settingsTabFromHash(hash: string): SettingsTabId {
  return SETTINGS_TAB_HASHES[hash.replace(/^#/, "")] ?? "overview";
}

const API_READ_ONLY_KEYS = new Set([
  "APP_MODE",
  "TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED",
  "SEED_DEMO_DATA",
  "DATABASE_URL",
  "NEXT_PUBLIC_API_URL",
  "NEXT_PUBLIC_WS_URL",
  "LLM_ALLOW_PRIVATE_ENDPOINTS",
  "LLM_ALLOW_INSECURE_ENDPOINTS",
  "LLM_ALLOWED_PROVIDER_HOSTS",
  "TICKET_RAG_SCOPE_KEY",
  "TICKET_RAG_V2_SCOPE_ALLOWLIST",
]);

const SSO_PORTAL_KEYS = new Set([
  "SSO_ENABLED", "SSO_PROVIDER", "SSO_ENTRA_TENANT_ID", "SSO_OKTA_DOMAIN",
  "SSO_OKTA_AUTH_SERVER_ID", "SSO_CLIENT_ID", "SSO_CLIENT_SECRET",
  "SSO_DISCOVERY_URL", "SSO_ALLOWED_DOMAINS", "SSO_ALLOWED_GROUP_IDS",
  "SSO_AUTO_PROVISION",
]);

type FreshserviceAuthMode = "api" | "oauth";
type MaintenanceWindowUnit = "days" | "weeks";
const FRESHSERVICE_DEFAULT_SCOPES = "freshservice.tickets.view freshservice.tickets.conversations.view freshservice.agents.manage freshservice.requesters.view";

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

function isAuthError(error: unknown) {
  return error instanceof APIError && error.status === 401;
}

function isForbiddenError(error: unknown) {
  return error instanceof APIError && error.status === 403;
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

const CONFIG_COLORS = [
  { value: "slate", label: "Slate", className: "bg-linen-500" },
  { value: "blue", label: "Blue", className: "bg-blue-500" },
  { value: "amber", label: "Amber", className: "bg-amber-500" },
  { value: "red", label: "Red", className: "bg-rust-500" },
  { value: "moss", label: "Moss", className: "bg-moss-500" },
  { value: "clay", label: "Clay", className: "bg-clay-500" },
] as const;

type ConfigColor = (typeof CONFIG_COLORS)[number]["value"];
type StatusLifecycle = "open" | "terminal";

const CONFIG_NAME_MAX_LENGTH = 100;
const PRIORITY_NAME_MAX_LENGTH = 32;
const CONFIG_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _-]*$/;
const CONFIG_LABEL_MAX_LENGTH = 100;
const CONFIG_SORT_ORDER_MAX = 10_000;
const PRIORITY_SLA_MIN_HOURS = 1;
const PRIORITY_SLA_MAX_HOURS = 8_760;
const PRIORITY_WEIGHT_MIN = 1;
const PRIORITY_WEIGHT_MAX = 1_000;

const CONFIG_COLOR_CLASSES: Record<string, string> = {
  ...Object.fromEntries(CONFIG_COLORS.map((option) => [option.value, option.className])),
  // Preserve an intentional visual for the legacy seeded status color.
  emerald: "bg-emerald-500",
};

function configColorClass(color: string) {
  return CONFIG_COLOR_CLASSES[color] || CONFIG_COLOR_CLASSES.slate;
}

function configErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

function isConfigurationAccessError(error: unknown) {
  return isAuthError(error) || isForbiddenError(error);
}

function nextConfigSortOrder(items: Array<{ sort_order: number }> | undefined) {
  const highest = (items || []).reduce((current, item) => (
    Number.isFinite(item.sort_order) ? Math.max(current, item.sort_order) : current
  ), -1);
  return Math.max(0, highest + 1);
}

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
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canAccessSettings = canAccessAdministration(authQuery.data);
  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
    enabled: canAccessSettings,
  });
  const catalogQuery = useQuery({
    queryKey: ["llm-catalog"],
    queryFn: api.getLlmCatalog,
    enabled: canAccessSettings,
  });
  const { data, isLoading, error: settingsError } = settingsQuery;
  const { data: catalog, error: catalogError } = catalogQuery;
  const { data: version } = useQuery({ queryKey: ["version"], queryFn: api.getVersion, staleTime: Infinity });
  const [form, setForm] = useState<Partial<SettingsType>>({});
  const [saved, setSaved] = useState(false);
  const [freshserviceAuthMode, setFreshserviceAuthMode] = useState<FreshserviceAuthMode>("api");
  const [repairWindowUnit, setRepairWindowUnit] = useState<MaintenanceWindowUnit>("days");
  const [repairWindowValue, setRepairWindowValue] = useState(7);
  const [activeTab, setActiveTab] = useState<SettingsTabId>("overview");
  const pendingHashScrollRef = useRef<string | null>(null);
  const appMode = ((form.APP_MODE || data?.APP_MODE) as string) || "demo";
  const productionOperationalSettingsReadOnly = false;
  const productionSecuritySettingsReadOnly = false;
  const configuredSsoProvider = ((form.SSO_PROVIDER as string) || "entra").trim().toLowerCase();
  const ssoProviderType = ["entra", "entra id", "azure ad", "azure active directory", "microsoft entra", "microsoft entra id"].includes(configuredSsoProvider)
    ? "entra"
    : configuredSsoProvider === "okta"
      ? "okta"
      : "oidc";
  const derivedSsoRedirectUri = (form.SSO_REDIRECT_URI as string)
    || ((form.FRONTEND_URL as string)?.trim().replace(/\/+$/, "")
      ? `${(form.FRONTEND_URL as string).trim().replace(/\/+$/, "")}/api/auth/sso/callback`
      : "");

  useEffect(() => {
    if (data) {
      setForm({
        ...data,
        ITSM_PROVIDER: "freshservice",
      });
      const hasOAuthApp = data.FRESHSERVICE_OAUTH_CLIENT_ID__set || data.FRESHSERVICE_OAUTH_CLIENT_SECRET__set;
      if (data.FRESHSERVICE_OAUTH_ACCESS_TOKEN__set || (!data.FRESHSERVICE_API_KEY__set && hasOAuthApp)) {
        setFreshserviceAuthMode("oauth");
      }
    }
  }, [data]);

  useEffect(() => {
    const syncTabFromHash = () => {
      const hashId = window.location.hash.replace(/^#/, "");
      pendingHashScrollRef.current = hashId || null;
      setActiveTab(settingsTabFromHash(hashId));
    };
    syncTabFromHash();
    window.addEventListener("hashchange", syncTabFromHash);
    return () => window.removeEventListener("hashchange", syncTabFromHash);
  }, []);

  useEffect(() => {
    const hashId = pendingHashScrollRef.current;
    if (!settingsQuery.isSuccess || !hashId || settingsTabFromHash(hashId) !== activeTab) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(hashId)?.scrollIntoView({ block: "start" });
      pendingHashScrollRef.current = null;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeTab, settingsQuery.isSuccess]);

  const selectSettingsTab = (tab: SettingsTabId) => {
    setActiveTab(tab);
    const config = SETTINGS_TABS.find((item) => item.id === tab);
    if (config) window.history.replaceState(window.history.state, "", `#${config.hash}`);
    window.requestAnimationFrame(() => document.getElementById(`settings-panel-${tab}`)?.scrollIntoView({ block: "start" }));
  };

  const handleSettingsTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const lastIndex = SETTINGS_TABS.length - 1;
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? lastIndex
        : event.key === "ArrowRight"
          ? (index + 1) % SETTINGS_TABS.length
          : (index - 1 + SETTINGS_TABS.length) % SETTINGS_TABS.length;
    const nextTab = SETTINGS_TABS[nextIndex];
    selectSettingsTab(nextTab.id);
    document.getElementById(`settings-tab-${nextTab.id}`)?.focus();
  };

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

  const authError = isAuthError(authQuery.error) || isAuthError(settingsError) || isAuthError(catalogError) || isAuthError(mutation.error);

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
    mutationFn: () => postMaintenanceAction(`/api/admin/sync/repair?window_unit=${repairWindowUnit}&window_value=${repairWindowValue}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["tickets"] }); },
  });

  const handleChange = (key: keyof SettingsType, value: string) => {
    if (mutation.isError) mutation.reset();
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const activeProviderId = useMemo(() => {
    const model = (form.DEFAULT_MODEL || "").trim();
    if (model.startsWith("custom/")) return "custom";
    return (catalog?.current_provider as string) || "foundry";
  }, [catalog, form.DEFAULT_MODEL]);

  const activeProvider: LlmProvider | undefined = catalog ? (catalog[activeProviderId] as LlmProvider) : undefined;
  const itProvider = "freshservice";
  const automationValue = (key: string) => {
    const value = form[key as keyof SettingsType] as string | undefined;
    if (value === "true") return true;
    if (value === "false") return false;
    return false;
  };
  const keyReady = (key: string) => {
    const value = form[key as keyof SettingsType];
    if (typeof value === "string" && value.trim() !== "" && !value.includes("****")) return true;
    const setFlag = data?.[`${key}__set`];
    return typeof setFlag === "boolean" ? setFlag : false;
  };
  const freshserviceAuthReady = freshserviceAuthMode === "oauth"
    ? keyReady("FRESHSERVICE_OAUTH_ACCESS_TOKEN")
    : keyReady("FRESHSERVICE_API_KEY");
  const freshserviceReady = Boolean(
    form.FRESHSERVICE_DOMAIN?.trim() &&
    freshserviceAuthReady
  );
  const isExternalProvider = true;
  const sendgridReady = keyReady("SENDGRID_API_KEY") && Boolean(form.SENDGRID_FROM_EMAIL?.trim());
  const baselineForm = useMemo<SettingsType | null>(() => data ? {
    ...data,
    ITSM_PROVIDER: "freshservice",
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (authError) {
      router.replace("/login?next=/settings");
      return;
    }
    const payload: Record<string, string> = {};
    for (const key of Object.keys(form)) {
      const v = form[key as keyof SettingsType];
      if (typeof v !== "string") continue;
      if (v === "" && ((!SSO_PORTAL_KEYS.has(key) && key !== "SENDGRID_REPLY_TO_EMAIL") || key === "SSO_CLIENT_SECRET")) continue;
      if (baselineForm && v === baselineForm[key as keyof SettingsType]) continue;
      if (v.includes("****")) continue;
      if (API_READ_ONLY_KEYS.has(key)) continue;
      payload[key] = v;
    }
    mutation.mutate(payload);
  };

  if (authQuery.isLoading || (canAccessSettings && isLoading)) {
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

  if (authQuery.error) {
    return (
      <ErrorState
        title="Session status could not be checked"
        description="Tickety OPS Tower could not determine whether this session may access administration controls."
        actionLabel="Retry session check"
        onRetry={() => void authQuery.refetch()}
        retrying={authQuery.isFetching}
      />
    );
  }

  if (isDemoAdministrationContext(authQuery.data)) {
    return <DemoAdministrationState version={version} />;
  }

  if (!canAccessSettings) {
    return (
      <ErrorState
        title="Administrator access required"
        description="System settings are available only to a signed-in administrator. Your current session does not have permission to view or change them."
      />
    );
  }

  if (isForbiddenError(settingsError)) {
    return (
      <ErrorState
        title="Administrator access required"
        description="System settings are available only to a signed-in administrator. Your current session does not have permission to view or change them."
      />
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
    <PageFrame className="max-w-6xl space-y-8">
      <PageHeader eyebrow="Administration" icon={<SettingsIcon className="h-5 w-5" />} title="System settings" description="Configure intelligence, ticketing, security, workflow, and operational maintenance." />

      {catalogError && !isAuthError(catalogError) && (
        <Alert variant="warning" title="Model catalog unavailable" action={<Button variant="secondary" size="sm" onClick={() => void catalogQuery.refetch()} pending={catalogQuery.isFetching} pendingLabel="Retrying…">Retry</Button>}>
          Saved settings are available, but provider and model choices may be incomplete until the catalog reconnects.
        </Alert>
      )}

      {appMode === "production" && (
        <Alert variant="info" title="Global admin settings enabled">
          Settings saved here become admin-approved runtime overrides. Static bootstrap settings such as runtime mode, database access, and public API wiring remain deployment-managed.
        </Alert>
      )}

      <div className="sticky top-20 z-20 -mx-1 rounded-xl border border-linen-400 bg-linen-50/95 p-1 shadow-sm backdrop-blur">
        <div role="tablist" aria-label="Settings sections" className="flex gap-1 overflow-x-auto">
          {SETTINGS_TABS.map((tab, index) => {
            const selected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                id={`settings-tab-${tab.id}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`settings-panel-${tab.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectSettingsTab(tab.id)}
                onKeyDown={(event) => handleSettingsTabKeyDown(event, index)}
                className={cn(
                  "inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-xs font-semibold transition-colors sm:min-h-10",
                  selected ? "bg-ink-700 text-white shadow-sm" : "text-ink-500 hover:bg-linen-200 hover:text-ink-700"
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <p className="-mt-5 text-xs text-ink-400" aria-live="polite">
        {SETTINGS_TABS.find((tab) => tab.id === activeTab)?.description}
      </p>

      <form onSubmit={handleSubmit} className="space-y-8">
        {SETTINGS_TABS.filter((tab) => tab.id !== activeTab).map((tab) => (
          <div
            key={tab.id}
            id={`settings-panel-${tab.id}`}
            role="tabpanel"
            aria-labelledby={`settings-tab-${tab.id}`}
            hidden
          />
        ))}
        {activeTab === "overview" && (
        <SettingsTabPanel tab="overview">
        <SettingsSection title="Configuration areas" subtitle="Open one focused area at a time; unsaved form changes remain available while you move between tabs">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SETTINGS_TABS.filter((tab) => tab.id !== "overview").map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => selectSettingsTab(tab.id)}
                className="group min-h-24 rounded-xl border border-linen-400 bg-linen-100 p-4 text-left transition-colors hover:border-clay-300 hover:bg-[var(--color-primary-soft)]"
              >
                <span className="block text-sm font-semibold text-ink-700 group-hover:text-semantic-primary">{tab.label}</span>
                <span className="mt-1 block text-xs leading-5 text-ink-500">{tab.description}</span>
              </button>
            ))}
          </div>
        </SettingsSection>

        {/* ═══ Consolidated Admin Status ═══ */}
        <SettingsSection id="settings-status" title="Status" subtitle="All operational checks are consolidated in one read-only admin view">
          <Link href="/settings/status" className="group flex items-center justify-between gap-4 rounded-xl border border-linen-400 bg-linen-100 p-4 transition-colors hover:border-clay-400 hover:bg-clay-50">
            <span className="flex min-w-0 items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--color-info-soft)] text-semantic-info"><Activity className="h-5 w-5" /></span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-ink-700">Open Admin Status</span>
                <span className="mt-1 block text-xs leading-5 text-ink-500">Check application readiness, AI tasks, ticket synchronization, search indexing, and integration connectivity. Warning and error cards can reveal their stored diagnostic logs.</span>
                <span className="mt-3 flex flex-wrap gap-2 text-[11px] font-medium text-ink-400">
                  <span className="rounded-full bg-linen-300 px-2 py-1">Application</span>
                  <span className="rounded-full bg-linen-300 px-2 py-1">AI</span>
                  <span className="rounded-full bg-linen-300 px-2 py-1">Ticket sync</span>
                  <span className="rounded-full bg-linen-300 px-2 py-1">Search</span>
                  <span className="rounded-full bg-linen-300 px-2 py-1">Integrations</span>
                </span>
              </span>
            </span>
            <span className="shrink-0 text-xs font-semibold text-semantic-primary group-hover:underline">Open status →</span>
          </Link>
        </SettingsSection>
        </SettingsTabPanel>
        )}

        {activeTab === "ai" && (
        <SettingsTabPanel tab="ai">
        {/* ═══ LLM Configuration ═══ */}
        <SettingsSection id="settings-ai" title="LLM Configuration" subtitle="Use Microsoft Foundry or one simplified custom OpenAI-compatible API">
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
                    disabled={productionOperationalSettingsReadOnly}
                    className={cn(
                      "min-h-[68px] rounded border px-3 py-2 text-left transition-colors",
                      productionOperationalSettingsReadOnly && "cursor-not-allowed opacity-70",
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

          <Field label={<DeploymentManagedLabel label="Default Model" managed={productionOperationalSettingsReadOnly} />}>
            {activeProvider ? (
              <fieldset disabled={productionOperationalSettingsReadOnly} className="contents">
                <SearchableSelect
                  value={form.DEFAULT_MODEL || ""}
                  options={activeProvider.models || []}
                  onChange={(v) => handleChange("DEFAULT_MODEL", v)}
                  placeholder={activeProvider.model_hint || "Select or search for a model…"}
                  disabled={productionOperationalSettingsReadOnly}
                />
              </fieldset>
            ) : (
              <input type="text" value={form.DEFAULT_MODEL || ""} onChange={(e) => handleChange("DEFAULT_MODEL", e.target.value)} placeholder="model id" className="input-base" disabled={productionOperationalSettingsReadOnly} />
            )}
          </Field>

          <div className="flex items-center justify-between">
            <span className="text-xs text-ink-500">
              {fetchedInfo ? `Last fetch: ${fetchedInfo.total_models} models from ${fetchedInfo.providers_queried.length} configured APIs` : "Models are fetched automatically from configured APIs and cached; use refresh to fetch now."}
            </span>
            <button type="button" onClick={() => refreshMut.mutate()} disabled={refreshMut.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-linen-400 text-xs font-medium text-ink-600 hover:bg-linen-200 disabled:opacity-50">
              {refreshMut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              {refreshMut.isPending ? "Fetching…" : "Fetch Latest Models"}
            </button>
          </div>

          {activeProvider?.env_keys.map((ek) => (
            <Field key={ek.key} label={<DeploymentManagedLabel label={ek.label} managed={productionOperationalSettingsReadOnly} />} ready={keyReady(ek.key)}>
              {ek.key === "FOUNDRY_AUTH_METHOD" ? (
                <select value={(form.FOUNDRY_AUTH_METHOD as string) || "api_key"} onChange={(e) => handleChange("FOUNDRY_AUTH_METHOD", e.target.value)} className="input-base" disabled={productionOperationalSettingsReadOnly}>
                  <option value="api_key">API key</option>
                  <option value="entra">Microsoft Entra ID</option>
                </select>
              ) : ek.secret ? (
                <SecretInput value={(form[ek.key as keyof SettingsType] as string) || ""} onChange={(v) => handleChange(ek.key as keyof SettingsType, v)} placeholder={ek.placeholder} disabled={productionOperationalSettingsReadOnly} />
              ) : (
                <input type="text" value={(form[ek.key as keyof SettingsType] as string) || ""} onChange={(e) => handleChange(ek.key as keyof SettingsType, e.target.value)} placeholder={ek.placeholder} className="input-base" disabled={productionOperationalSettingsReadOnly} />
              )}
            </Field>
          ))}
        </SettingsSection>

        {/* ═══ AI Automation Toggles ═══ */}
        <SettingsSection id="settings-automation" title="AI Automation" subtitle="Toggle which ambient AI agents run automatically on incoming tickets">
          <div className="space-y-2">
            {[
              { key: "AUTO_SUMMARIZE_ENABLED", label: "Auto-Summarization", desc: "Generate 2-3 sentence case summaries for support managers" },
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
          <div className="mt-4 flex flex-col gap-3 rounded-xl border border-linen-400 bg-linen-100 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div><p className="text-sm font-semibold text-ink-700">Routing &amp; triage control plane</p><p className="mt-1 text-xs leading-5 text-ink-500">Manage auto-triage, advisory routing, structured rules, and local agent team mappings in the protected operations workspace.</p></div>
            <Link href="/routing" className="inline-flex min-h-10 shrink-0 items-center justify-center rounded-lg bg-semantic-primary px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-semantic-primary-hover">Open routing &amp; triage</Link>
          </div>
        </SettingsSection>
        </SettingsTabPanel>
        )}

        {activeTab === "integrations" && (
        <SettingsTabPanel tab="integrations">
        {/* ═══ Ticketing Mode ═══ */}
        <SettingsSection id="settings-ticketing" title="Freshservice sidecar" subtitle="Tickety OPS Tower imports Freshservice records for local intelligence and never writes back to the system of record">
          <Field label="Provider">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {PROVIDER_OPTIONS.map((provider) => {
                const selected = itProvider === provider.value;
                  const ready = freshserviceReady;
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
            <>
            <ConnectionPanel
              title="Connect Freshservice"
              description="Use a Freshservice domain plus one authentication method. Only ticket and agent reads are implemented."
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
                <Field label={<DeploymentManagedLabel label="Freshservice API Key" managed={productionOperationalSettingsReadOnly} />} ready={keyReady("FRESHSERVICE_API_KEY")}>
                  <SecretInput value={form.FRESHSERVICE_API_KEY || ""} onChange={(v) => handleChange("FRESHSERVICE_API_KEY", v)} placeholder="Paste API key" disabled={productionOperationalSettingsReadOnly} />
                </Field>
              ) : (
                <FreshserviceOAuthSetup form={form} onChange={handleChange} keyReady={keyReady} productionSettingsReadOnly={productionOperationalSettingsReadOnly} />
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
                  <Field label={<DeploymentManagedLabel label="Webhook Secret" managed={productionOperationalSettingsReadOnly} />} ready={keyReady("WEBHOOK_SECRET")}>
                    <SecretInput value={form.WEBHOOK_SECRET || ""} onChange={(v) => handleChange("WEBHOOK_SECRET", v)} placeholder="Shared secret" disabled={productionOperationalSettingsReadOnly} />
                  </Field>
                  <Field label="Sync Interval" ready={Boolean(form.SYNC_INTERVAL_SECONDS?.trim())}>
                    <input type="number" min={10} value={form.SYNC_INTERVAL_SECONDS || ""} onChange={(e) => handleChange("SYNC_INTERVAL_SECONDS", e.target.value)} placeholder="60" className="input-base" />
                  </Field>
                  <Field label="Minimum request spacing" ready={Boolean(form.FRESHSERVICE_MIN_INTERVAL_SECONDS?.trim())}>
                    <input type="number" min={0.25} step={0.05} value={form.FRESHSERVICE_MIN_INTERVAL_SECONDS || ""} onChange={(e) => handleChange("FRESHSERVICE_MIN_INTERVAL_SECONDS", e.target.value)} placeholder="1.6 seconds" className="input-base" />
                  </Field>
                  <Field label="API budget reserve" ready={Boolean(form.FRESHSERVICE_RATE_LIMIT_RESERVE?.trim())}>
                    <input type="number" min={2} value={form.FRESHSERVICE_RATE_LIMIT_RESERVE || ""} onChange={(e) => handleChange("FRESHSERVICE_RATE_LIMIT_RESERVE", e.target.value)} placeholder="10 credits" className="input-base" />
                  </Field>
                  <Field label="Current pages per sync" ready={Boolean(form.FRESHSERVICE_RECENT_PAGES_PER_SYNC?.trim())}>
                    <input type="number" min={1} max={10} value={form.FRESHSERVICE_RECENT_PAGES_PER_SYNC || ""} onChange={(e) => handleChange("FRESHSERVICE_RECENT_PAGES_PER_SYNC", e.target.value)} placeholder="2" className="input-base" />
                  </Field>
                  <Field label="Admin old-ticket pages per sync" ready={Boolean(form.FRESHSERVICE_HISTORY_PAGES_PER_SYNC?.trim())}>
                    <input type="number" min={1} max={5} value={form.FRESHSERVICE_HISTORY_PAGES_PER_SYNC || ""} onChange={(e) => handleChange("FRESHSERVICE_HISTORY_PAGES_PER_SYNC", e.target.value)} placeholder="1" className="input-base" />
                  </Field>
                  <Field label="Conversation threads per sync" ready={Boolean(form.FRESHSERVICE_CONVERSATIONS_PER_SYNC?.trim())}>
                    <input type="number" min={0} max={5} value={form.FRESHSERVICE_CONVERSATIONS_PER_SYNC || ""} onChange={(e) => handleChange("FRESHSERVICE_CONVERSATIONS_PER_SYNC", e.target.value)} placeholder="1" className="input-base" />
                  </Field>
                  <Field label="Attachments per sync" ready={Boolean(form.FRESHSERVICE_ATTACHMENTS_PER_SYNC?.trim())}>
                    <input type="number" min={0} max={20} value={form.FRESHSERVICE_ATTACHMENTS_PER_SYNC || ""} onChange={(e) => handleChange("FRESHSERVICE_ATTACHMENTS_PER_SYNC", e.target.value)} placeholder="2" className="input-base" />
                  </Field>
                  <Field label="Attachment storage" ready={form.ATTACHMENT_STORAGE_PROVIDER === "azure_blob"}>
                    <select value={form.ATTACHMENT_STORAGE_PROVIDER || ""} onChange={(e) => handleChange("ATTACHMENT_STORAGE_PROVIDER", e.target.value)} className="input-base">
                      <option value="">Disabled until storage is ready</option>
                      <option value="azure_blob">Azure Blob Storage</option>
                    </select>
                  </Field>
                  <Field label="Azure Blob account URL" ready={Boolean(form.AZURE_STORAGE_ACCOUNT_URL?.trim())}>
                    <input type="url" value={form.AZURE_STORAGE_ACCOUNT_URL || ""} onChange={(e) => handleChange("AZURE_STORAGE_ACCOUNT_URL", e.target.value)} placeholder="https://account.blob.core.windows.net" className="input-base" />
                  </Field>
                  <Field label="Private container" ready={Boolean(form.AZURE_STORAGE_CONTAINER?.trim())}>
                    <input type="text" value={form.AZURE_STORAGE_CONTAINER || ""} onChange={(e) => handleChange("AZURE_STORAGE_CONTAINER", e.target.value.toLowerCase())} placeholder="tickety-attachments" className="input-base" />
                  </Field>
                  <Field label="Maximum attachment bytes" ready={Boolean(form.ATTACHMENT_MAX_BYTES?.trim())}>
                    <input type="number" min={1048576} max={104857600} value={form.ATTACHMENT_MAX_BYTES || ""} onChange={(e) => handleChange("ATTACHMENT_MAX_BYTES", e.target.value)} placeholder="52428800" className="input-base" />
                  </Field>
                </div>
                <p className="mt-3 text-xs leading-5 text-ink-400">Discovery excludes embedded resources to conserve Freshservice API credits. Full content and attachment metadata are hydrated in the bounded conversation lane. Azure access uses the worker identity or deployment-managed service-principal credentials; the container must remain private.</p>
              </AdvancedPanel>
            </ConnectionPanel>

            </>
          )}

        </SettingsSection>

        {/* ═══ SLA Targets ═══ */}
        <SettingsSection title="SLA Targets" subtitle="Set resolution time targets per priority level. Used by SLA clocks and escalation risk scoring.">
          <div className="grid grid-cols-1 gap-4 xs:grid-cols-2 md:grid-cols-4">
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
        </SettingsTabPanel>
        )}

        {activeTab === "workspace" && (
        <SettingsTabPanel tab="workspace">
        {/* ═══ Category Management ═══ */}
        <CategorySection />

        {/* ═══ Organization / Branding ═══ */}
        <SettingsSection id="settings-workspace" title="Organization" subtitle="Customize the workspace name and branding shown across Tickety OPS Tower">
          <Field label="Organization Name">
            <input type="text" value={form.ORG_NAME || ""} onChange={(e) => handleChange("ORG_NAME", e.target.value)} placeholder="Acme IT Support" className="input-base" />
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Logo URL">
              <input type="text" value={form.ORG_LOGO_URL || ""} onChange={(e) => handleChange("ORG_LOGO_URL", e.target.value)} placeholder="https://…" className="input-base" />
            </Field>
            <Field label="Primary Color">
              <input type="text" value={form.ORG_PRIMARY_COLOR || ""} onChange={(e) => handleChange("ORG_PRIMARY_COLOR", e.target.value)} placeholder="#6B8E5A" className="input-base" />
            </Field>
          </div>
        </SettingsSection>

        {/* ═══ Custom Statuses ═══ */}
        <StatusConfigSection canManage={canAccessSettings} />

        {/* ═══ Custom Priorities ═══ */}
        <PriorityConfigSection canManage={canAccessSettings} />

        {/* ═══ Notifications ═══ */}
        <NotificationSection />
        </SettingsTabPanel>
        )}

        {activeTab === "email" && (
        <SettingsTabPanel tab="email">
        {/* ═══ SendGrid Email ═══ */}
        <SettingsSection id="settings-email" title="SendGrid email" subtitle="Configure verified sender identity, reply routing, and per-user delivery limits">
          <div className="flex flex-col gap-3 rounded-xl border border-linen-400 bg-linen-100 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-semantic-primary shadow-sm"><Mail className="h-5 w-5" aria-hidden="true" /></span>
              <div>
                <p className="text-sm font-semibold text-ink-700">Outbound email via SendGrid</p>
                <p className="mt-1 text-xs leading-5 text-ink-500">The API key remains server-side and is always masked after saving. Use a sender address authenticated in your SendGrid account.</p>
              </div>
            </div>
            {sendgridReady ? <ReadyPill /> : <OffPill />}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="SendGrid API key" ready={keyReady("SENDGRID_API_KEY")}>
              <SecretInput value={form.SENDGRID_API_KEY || ""} onChange={(value) => handleChange("SENDGRID_API_KEY", value)} placeholder="SG.…" />
            </Field>
            <Field label="Verified sender email" ready={Boolean(form.SENDGRID_FROM_EMAIL?.trim())}>
              <input type="email" value={form.SENDGRID_FROM_EMAIL || ""} onChange={(event) => handleChange("SENDGRID_FROM_EMAIL", event.target.value)} placeholder="support@example.com" className="input-base" />
            </Field>
            <Field label="Sender name">
              <input type="text" maxLength={100} value={form.SENDGRID_FROM_NAME || ""} onChange={(event) => handleChange("SENDGRID_FROM_NAME", event.target.value)} placeholder={form.ORG_NAME || "Tickety OPS Tower"} className="input-base" />
            </Field>
            <Field label="Reply-to email">
              <input type="email" value={form.SENDGRID_REPLY_TO_EMAIL || ""} onChange={(event) => handleChange("SENDGRID_REPLY_TO_EMAIL", event.target.value)} placeholder="helpdesk@example.com (optional)" className="input-base" />
            </Field>
            <Field label="Sends per user / minute">
              <input type="number" min={1} max={60} value={form.EMAIL_SENDS_PER_MINUTE || "5"} onChange={(event) => handleChange("EMAIL_SENDS_PER_MINUTE", event.target.value)} className="input-base" />
            </Field>
            <Field label="Recipients per user / day">
              <input type="number" min={1} max={10000} value={form.EMAIL_RECIPIENTS_PER_DAY || "500"} onChange={(event) => handleChange("EMAIL_RECIPIENTS_PER_DAY", event.target.value)} className="input-base" />
            </Field>
          </div>

          <div className="flex flex-col gap-3 rounded-xl border border-linen-400 bg-linen-50 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs leading-5 text-ink-500">Once the API key and verified sender are saved, signed-in team members can address separate private deliveries to agents or synced requesters.</p>
            <Link href="/email" className="inline-flex min-h-10 shrink-0 items-center justify-center rounded-lg bg-semantic-primary px-4 text-sm font-semibold text-white hover:bg-semantic-primary-hover">Open email composer</Link>
          </div>
        </SettingsSection>
        </SettingsTabPanel>
        )}

        {activeTab === "access" && (
        <SettingsTabPanel tab="access">
        {/* ═══ Security & Auth ═══ */}
        <SettingsSection id="settings-access" title="Security & Authentication" subtitle="Require login and configure Single Sign-On (OIDC) for production deployments">
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
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label={<DeploymentManagedLabel label="CORS Allow Origins" managed={productionSecuritySettingsReadOnly} />}>
              <input
                type="text"
                value={form.CORS_ALLOW_ORIGINS || ""}
                onChange={(e) => handleChange("CORS_ALLOW_ORIGINS", e.target.value)}
                placeholder="https://support.example.com"
                className="input-base"
                disabled={productionSecuritySettingsReadOnly}
              />
            </Field>
            <Field label={<DeploymentManagedLabel label="Cookie SameSite" managed={productionSecuritySettingsReadOnly} />}>
              <select
                value={(form.COOKIE_SAMESITE as string) || "lax"}
                onChange={(e) => handleChange("COOKIE_SAMESITE", e.target.value)}
                className="input-base"
                disabled={productionSecuritySettingsReadOnly}
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
            disabled={productionSecuritySettingsReadOnly}
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
            disabled={productionSecuritySettingsReadOnly}
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
            desc="Allow users to sign in through Microsoft Entra ID, Okta, or another OpenID Connect provider."
            value={(form.SSO_ENABLED as string) === "true"}
            onChange={(v) => {
              handleChange("SSO_ENABLED", v ? "true" : "false");
              if (v && !form.SSO_PROVIDER) handleChange("SSO_PROVIDER", "entra");
            }}
          />

          {(form.SSO_ENABLED as string) === "true" && (
            <div className="space-y-4 pt-2">
              <Field label="Identity Provider">
                <select value={ssoProviderType} onChange={(e) => handleChange("SSO_PROVIDER", e.target.value)} className="input-base">
                  <option value="entra">Microsoft Entra ID</option>
                  <option value="okta">Okta</option>
                  <option value="oidc">Generic OpenID Connect</option>
                </select>
              </Field>
              {ssoProviderType === "entra" && (
                <Field label="Entra Tenant ID">
                  <input type="text" value={form.SSO_ENTRA_TENANT_ID || ""} onChange={(e) => handleChange("SSO_ENTRA_TENANT_ID", e.target.value)} placeholder="Directory (tenant) ID" className="input-base" />
                  <span className="block text-xs leading-5 text-ink-400">Use the Directory (tenant) ID GUID from the app registration. Multi-tenant authorities are intentionally not accepted.</span>
                </Field>
              )}
              {ssoProviderType === "okta" && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Okta Domain">
                    <input type="text" value={form.SSO_OKTA_DOMAIN || ""} onChange={(e) => handleChange("SSO_OKTA_DOMAIN", e.target.value)} placeholder="company.okta.com" className="input-base" />
                  </Field>
                  <Field label="Authorization Server">
                    <input type="text" value={form.SSO_OKTA_AUTH_SERVER_ID || "org"} onChange={(e) => handleChange("SSO_OKTA_AUTH_SERVER_ID", e.target.value)} placeholder="org" className="input-base" />
                    <span className="block text-xs leading-5 text-ink-400">Use <code>org</code> for standard SSO, or enter a configured custom authorization-server ID.</span>
                  </Field>
                </div>
              )}
              <Field label="Client ID">
                <input type="text" value={form.SSO_CLIENT_ID || ""} onChange={(e) => handleChange("SSO_CLIENT_ID", e.target.value)} placeholder="OIDC client ID" className="input-base" />
              </Field>
              <Field label="Client Secret">
                <SecretInput value={form.SSO_CLIENT_SECRET || ""} onChange={(v) => handleChange("SSO_CLIENT_SECRET", v)} placeholder="OIDC client secret" />
              </Field>
              {ssoProviderType === "oidc" && (
                <Field label="Discovery URL">
                  <input type="text" value={form.SSO_DISCOVERY_URL || ""} onChange={(e) => handleChange("SSO_DISCOVERY_URL", e.target.value)} placeholder="https://identity.example/.well-known/openid-configuration" className="input-base" />
                </Field>
              )}
              <Field label="Sign-in Redirect URI">
                <input type="text" value={derivedSsoRedirectUri} readOnly className="input-base" aria-describedby="sso-redirect-help" />
                <span id="sso-redirect-help" className="block text-xs leading-5 text-ink-400">Copy this exact Web sign-in redirect URI into the Entra app registration or Okta app integration. It is derived from Frontend URL.</span>
              </Field>
              <Field label="Allowed Email Domains">
                <input type="text" value={form.SSO_ALLOWED_DOMAINS || ""} onChange={(e) => handleChange("SSO_ALLOWED_DOMAINS", e.target.value)} placeholder="company.com,subsidiary.com" className="input-base" />
              </Field>
              <Field label="Allowed Group IDs">
                <input type="text" value={form.SSO_ALLOWED_GROUP_IDS || ""} onChange={(e) => handleChange("SSO_ALLOWED_GROUP_IDS", e.target.value)} placeholder={ssoProviderType === "entra" ? "Entra IT agents group Object ID" : "Comma-separated provider group IDs"} className="input-base" />
                <span className="block text-xs leading-5 text-ink-400">When set, sign-in is allowed only when a verified group claim contains one of these immutable IDs.</span>
              </Field>
              <ToggleRow
                label="Auto-Provision SSO Users"
                desc="Create new active agent accounts for trusted SSO domains. Keep disabled when accounts should be pre-approved."
                value={(form.SSO_AUTO_PROVISION as string) === "true"}
                onChange={(v) => handleChange("SSO_AUTO_PROVISION", v ? "true" : "false")}
              />
              <p className="text-xs leading-5 text-ink-400">Entra and Okta discovery endpoints are generated automatically. Client secrets are stored as masked administrator settings and are never returned to the browser.</p>
            </div>
          )}
        </SettingsSection>

        <SettingsSection title="User & IAM" subtitle="Manage who can access Tickety OPS Tower and what operational permissions they receive.">
          <div className="rounded-xl border border-linen-400 bg-linen-100 p-4 sm:p-5">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="max-w-2xl">
                <div className="flex items-center gap-2 text-sm font-semibold text-ink-700"><Users className="h-4 w-4 text-semantic-primary" aria-hidden="true" />Team access management</div>
                <p className="mt-2 text-sm leading-6 text-ink-500">Add, update, and deactivate team accounts from the agent roster. Admins manage configuration and access; supervisors oversee queues and intelligence in production; agents work assigned tickets.</p>
                {appMode === "demo" && <p className="mt-3 text-xs leading-5 text-ink-400">Demo administrators can manage roles and account status. Existing account passwords are not editable in demo mode.</p>}
              </div>
              <Link href="/agents" className="inline-flex min-h-10 shrink-0 items-center justify-center rounded-lg bg-semantic-primary px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-semantic-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2">Manage users &amp; roles</Link>
            </div>
          </div>
        </SettingsSection>
        </SettingsTabPanel>
        )}

        {activeTab === "system" && (
        <SettingsTabPanel tab="system">
        {/* ═══ System Maintenance ═══ */}
        <SettingsSection id="settings-system" title="System Maintenance" subtitle="Run bounded AI maintenance only for tickets created inside the selected recent window">
          <div className="space-y-3">
            <MaintenanceButton
              label="Repair AI Gaps"
              description="Queue missing summaries and resolution plans only for tickets created inside the selected recent window."
              icon={Zap}
              mutation={repairMut}
              loadingText="Repairing…"
              windowUnit={repairWindowUnit}
              windowValue={repairWindowValue}
              onWindowUnitChange={(unit) => { setRepairWindowUnit(unit); setRepairWindowValue((value) => Math.min(value, unit === "days" ? 7 : 4)); }}
              onWindowValueChange={setRepairWindowValue}
              resultFormatter={(r: any) => `Queued ${r.queued ?? 0} ticket${r.queued === 1 ? "" : "s"} from the selected ${r.window_days ?? 0}-day window`}
            />
          </div>
        </SettingsSection>
        </SettingsTabPanel>
        )}

        {/* ═══ Save Bar ═══ */}
        {(isDirty || saved || mutation.isError) && <div className="sticky bottom-4 z-30 flex flex-col gap-3 rounded-xl border border-linen-400 bg-linen-50/95 px-4 py-3 shadow-[var(--shadow-raised)] backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-ink-500">{isDirty ? "You have unsaved configuration changes." : "Configuration is up to date."}</p>
          <div className="flex items-center justify-end gap-3">
          {saved && (
            <span role="status" className="flex items-center gap-1.5 text-sm text-moss-600">
              <CheckCircle2 className="w-4 h-4" /> Saved
            </span>
          )}
          {mutation.isError && (
            <span role="alert" className="flex items-center gap-1.5 text-sm text-rust-500">
              <AlertCircle className="w-4 h-4" /> {mutation.error instanceof Error ? mutation.error.message : "Failed to save"}
            </span>
          )}
          {isDirty && <Button type="button" variant="secondary" disabled={mutation.isPending} onClick={() => { if (baselineForm) setForm(baselineForm); mutation.reset(); setSaved(false); }}>Discard</Button>}
          <Button type="submit" disabled={!isDirty} pending={mutation.isPending} pendingLabel="Saving…" leadingIcon={<Save className="h-4 w-4" />}>
            Save Changes
          </Button>
          </div>
        </div>}
      </form>
    </PageFrame>
  );
}

function DemoAdministrationState({ version }: { version?: BuildInfo }) {
  return (
    <PageFrame className="max-w-5xl space-y-8">
      <PageHeader eyebrow="Administration" icon={<SettingsIcon className="h-5 w-5" />} title="System settings" description="Sign in with a demo administrator account to configure this demo workspace." />

      <div className="rounded-xl border border-clay-400/30 bg-clay-400/5 p-6 sm:p-8" role="status">
        <div className="flex items-start gap-4">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white text-clay-500 shadow-sm">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-clay-600">Demo administrator access</p>
            <h2 className="mt-1 text-xl font-semibold text-ink-700">Sign in to manage this demo</h2>
            <p className="mt-2 text-sm leading-6 text-ink-500">
              Configuration, integrations, and user access are available to an active demo administrator. The public demo session and demo supervisors remain read-only for protected administration features.
            </p>
          </div>
        </div>
      </div>

      <SettingsSection title="Runtime information" subtitle="This public information confirms which application build is running.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <InfoTile label="Mode" value="Demo" />
          <InfoTile label="Version" value={version?.version || "—"} />
          <InfoTile label="Build SHA" value={version?.build_sha || "—"} mono />
        </div>
      </SettingsSection>
    </PageFrame>
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
      <span className="min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]" title={label}>{label}</span>
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
  const authMut = useMutation({ mutationFn: api.getOAuthAuthorizeUrl, onSuccess: (res) => window.open(res.url, "_blank", "width=700,height=600,noopener,noreferrer") });
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
        <input type="text" value={form.FRESHSERVICE_OAUTH_SCOPES || FRESHSERVICE_DEFAULT_SCOPES} readOnly aria-readonly="true" className="input-base bg-linen-100" />
        <span className="block text-xs leading-5 text-ink-400">Scopes are fixed to the read-only allowlist. Agent and requester scopes only populate the separate external directory; use a view-only Freshservice integration role as an additional guard.</span>
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
        <div className="rounded border border-rust-400/30 bg-rust-400/10 p-3 text-sm text-rust-600">
          {authMut.error instanceof Error ? authMut.error.message : "Failed to get authorization URL"}
        </div>
      )}
    </div>
  );
}

// ═══ Reusable Section Wrapper ════════════════════════════════

function SettingsTabPanel({ tab, children }: { tab: SettingsTabId; children: React.ReactNode }) {
  return (
    <div
      id={`settings-panel-${tab}`}
      role="tabpanel"
      aria-labelledby={`settings-tab-${tab}`}
      className="scroll-mt-36 space-y-8"
    >
      {children}
    </div>
  );
}

function SettingsSection({ id, title, subtitle, children }: { id?: string; title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-36 space-y-5 rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-6">
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
  void managed;
  return label;
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

function MaintenanceButton({ label, description, icon: Icon, mutation, loadingText, windowUnit, windowValue, onWindowUnitChange, onWindowValueChange, resultFormatter }: {
  label: string; description: string; icon: React.ComponentType<{ className?: string }>;
  mutation: any; loadingText: string; windowUnit: MaintenanceWindowUnit; windowValue: number;
  onWindowUnitChange: (unit: MaintenanceWindowUnit) => void;
  onWindowValueChange: (value: number) => void;
  resultFormatter: (r: any) => string;
}) {
  const maximum = windowUnit === "days" ? 7 : 4;
  return (
    <div className="flex flex-col gap-3 rounded border border-linen-400 p-3 sm:flex-row sm:items-center sm:justify-between">
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
      <div className="flex shrink-0 flex-wrap items-end gap-2 sm:ml-3 sm:justify-end">
        <label className="text-[11px] font-medium text-ink-500">Unit
          <select value={windowUnit} onChange={(event) => onWindowUnitChange(event.target.value as MaintenanceWindowUnit)} disabled={mutation.isPending} className="input-base mt-1 min-h-9 w-24 py-1 text-xs">
            <option value="days">Days</option>
            <option value="weeks">Weeks</option>
          </select>
        </label>
        <label className="text-[11px] font-medium text-ink-500">Window
          <select value={windowValue} onChange={(event) => onWindowValueChange(Number(event.target.value))} disabled={mutation.isPending} className="input-base mt-1 min-h-9 w-20 py-1 text-xs">
            {Array.from({ length: maximum }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending} className="inline-flex min-h-9 items-center gap-1.5 rounded border border-linen-400 px-3 py-1.5 text-xs font-medium text-ink-600 hover:bg-linen-200 disabled:opacity-50">
          {mutation.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
          {mutation.isPending ? loadingText : "Run"}
        </button>
      </div>
    </div>
  );
}

// ═══ Category Management Section ════════════════════════════

function CategorySection() {
  const queryClient = useQueryClient();
  const { data: categories, isLoading } = useQuery({ queryKey: queryKeys.ticketCategories, queryFn: api.getCategories });
  const [showForm, setShowForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newColor, setNewColor] = useState("slate");

  const createMut = useMutation({
    mutationFn: () => api.createCategory(newName, newDesc, newColor),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.ticketCategories });
      setNewName(""); setNewDesc(""); setNewColor("slate"); setShowForm(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: api.deleteCategory,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.ticketCategories }),
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
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [userType, setUserType] = useState<"" | "agent" | "requester">("");
  const [pageSize, setPageSize] = useState(25);
  const [offset, setOffset] = useState(0);
  const directoryQuery = useQuery({
    queryKey: ["external-users", search, userType, pageSize, offset],
    queryFn: () => api.getExternalUsers({ search, userType, limit: pageSize, offset }),
  });
  const syncMut = useMutation({
    mutationFn: api.syncExternalUsers,
    onSuccess: () => {
      setOffset(0);
      void queryClient.invalidateQueries({ queryKey: ["external-users"] });
    },
  });
  const directory = directoryQuery.data;
  const users = directory?.users ?? [];
  const total = directory?.total ?? 0;
  const firstResult = total > 0 ? offset + 1 : 0;
  const lastResult = Math.min(offset + users.length, total);
  const hasFilters = Boolean(search || userType);
  const result = syncMut.data?.result;
  const summary = result
    ? [
        `${result.total.toLocaleString()} fetched`,
        `${result.created.toLocaleString()} new`,
        `${result.updated.toLocaleString()} updated`,
        `${result.unchanged.toLocaleString()} unchanged`,
        result.deactivated > 0 ? `${result.deactivated.toLocaleString()} deactivated` : null,
        result.errors > 0 ? `${result.errors.toLocaleString()} errors` : null,
      ].filter(Boolean).join(", ")
    : null;

  useEffect(() => {
    if (directory && directory.total > 0 && directory.users.length === 0 && offset >= directory.total) {
      setOffset(Math.floor((directory.total - 1) / pageSize) * pageSize);
    }
  }, [directory, offset, pageSize]);

  const applySearch = () => {
    setSearch(searchInput.trim());
    setOffset(0);
  };

  const selectUserType = (nextType: "" | "agent" | "requester") => {
    setUserType(nextType);
    setOffset(0);
  };

  const clearFilters = () => {
    setSearchInput("");
    setSearch("");
    setUserType("");
    setOffset(0);
  };

  return (
    <SettingsSection
      id="settings-directory"
      title="External ITSM directory"
      subtitle="Browse a large provider-owned directory without loading every agent and requester at once"
    >
      <div className="flex flex-col gap-4 rounded-xl border border-linen-400 bg-linen-100 p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-semantic-primary shadow-sm"><Users className="h-5 w-5" aria-hidden="true" /></span>
          <div className="min-w-0">
          <p className="text-sm font-semibold text-ink-700">Separate identity domain</p>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-ink-500">
            This directory is a read-only snapshot for ticket context. Tickety OPS Tower sign-in, roles, passwords, profiles, and local assignments remain controlled only from the local user roster.
          </p>
          </div>
        </div>
        <Button
          type="button"
          onClick={() => syncMut.mutate()}
          disabled={syncMut.isPending}
          leadingIcon={<Download className={cn("h-4 w-4", syncMut.isPending && "animate-pulse")} />}
        >
          {syncMut.isPending ? "Refreshing…" : "Refresh directory"}
        </Button>
      </div>

      {syncMut.isError && (
        <Alert variant="danger" title="Directory refresh failed">
          {syncMut.error instanceof Error ? syncMut.error.message : "The provider directory could not be refreshed."}
        </Alert>
      )}
      {result && (
        <Alert variant={result.errors > 0 ? "warning" : "success"} title={result.errors > 0 ? "Refresh completed with errors" : "Directory refreshed"}>
          {summary}
          {result.error_details.length > 0 && <span className="mt-1 block text-xs">{result.error_details.slice(0, 3).join(", ")}</span>}
        </Alert>
      )}

      <div className="space-y-3 rounded-xl border border-linen-400 bg-linen-50 p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 flex-1" role="search" aria-label="Search external ITSM directory">
            <label className="relative block max-w-xl">
              <span className="sr-only">Search external ITSM directory</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
              <input
                type="search"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applySearch();
                  }
                }}
                className="input-base input-search pr-24"
                placeholder="Search name, email, title, or provider ID"
              />
              <button type="button" onClick={applySearch} className="absolute right-1.5 top-1/2 min-h-8 -translate-y-1/2 rounded-md bg-ink-700 px-3 text-xs font-semibold text-white hover:bg-ink-600">Search</button>
            </label>
          </div>
          <p className="text-xs text-ink-500" aria-live="polite">
            {directoryQuery.isLoading
              ? "Loading directory…"
              : directoryQuery.isError
                ? "Directory unavailable"
                : `${total.toLocaleString()} matching ${total === 1 ? "entry" : "entries"}`}
          </p>
        </div>

        <div className="flex flex-col gap-3 border-t border-linen-300 pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap gap-2" aria-label="Filter directory by identity type">
            {([
              ["", "All identities"],
              ["agent", "Agents"],
              ["requester", "Requesters"],
            ] as const).map(([value, label]) => (
              <button
                key={value || "all"}
                type="button"
                aria-pressed={userType === value}
                onClick={() => selectUserType(value)}
                className={cn(
                  "min-h-9 rounded-full border px-3 text-xs font-semibold transition-colors",
                  userType === value
                    ? "border-clay-300 bg-[var(--color-primary-soft)] text-semantic-primary"
                    : "border-linen-400 text-ink-500 hover:bg-linen-200 hover:text-ink-700"
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            {hasFilters && <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>Clear filters</Button>}
            <label className="flex items-center gap-2 text-xs font-medium text-ink-500">
              Rows
              <select
                value={pageSize}
                onChange={(event) => { setPageSize(Number(event.target.value)); setOffset(0); }}
                className="input-base min-h-9 w-20 py-1 text-xs"
              >
                {[25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
              </select>
            </label>
          </div>
        </div>
      </div>

      {directoryQuery.isLoading ? (
        <div className="space-y-2">{Array.from({ length: 6 }, (_, item) => <Skeleton key={item} className="h-12 w-full" />)}</div>
      ) : directoryQuery.isError ? (
        <ErrorState
          title="External directory could not be loaded"
          description="No provider identities are being shown. Retry the current filtered page."
          actionLabel="Retry directory"
          onRetry={() => void directoryQuery.refetch()}
          retrying={directoryQuery.isFetching}
        />
      ) : users.length > 0 ? (
        <>
          <div className="grid gap-3 md:hidden">
            {users.map((externalUser) => (
              <DataListCard key={externalUser.id}>
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0 flex-1"><ListText text={externalUser.name} lines={2} className="font-semibold leading-5 text-ink-700" /><ListText text={externalUser.title || "Title not provided"} lines={2} className="mt-1 text-xs text-ink-400" /></div>
                  <span className="shrink-0 rounded border border-linen-400 px-2 py-0.5 text-[11px] font-semibold capitalize text-ink-600">{externalUser.user_type}</span>
                </div>
                <dl className="mt-4 grid gap-3 border-t border-linen-300 pt-3 text-xs xs:grid-cols-2">
                  <div className="min-w-0"><dt className="text-ink-400">Email</dt><dd className="mt-1"><ListText text={externalUser.email || "Not provided"} lines="wrap" className="text-ink-600" /></dd></div>
                  <div className="min-w-0"><dt className="text-ink-400">Provider identity</dt><dd className="mt-1 capitalize text-ink-600">{externalUser.provider}</dd><dd><ListText text={externalUser.external_id} lines="wrap" className="mt-0.5 font-mono text-[11px] text-ink-400" /></dd></div>
                </dl>
              </DataListCard>
            ))}
          </div>
          <DataTableViewport label="External ITSM directory current page" className="hidden rounded-xl border border-linen-400 md:block">
          <DataTable className="min-w-[640px]">
            <colgroup><col className="w-[34%]" /><col className="w-[30%]" /><col className="w-[22%]" /><col className="w-[14%]" /></colgroup>
            <thead>
              <tr className="border-b border-linen-400 bg-linen-200">
                <th className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-ink-500">Provider user</th>
                <th className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-ink-500">Contact</th>
                <th className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-ink-500">Directory identity</th>
                <th className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-ink-500">Type</th>
              </tr>
            </thead>
            <tbody>
              {users.map((externalUser) => (
                <tr key={externalUser.id} className="border-b border-linen-300 last:border-0 hover:bg-linen-200">
                  <td className="px-4 py-3"><ListText text={externalUser.name} lines={2} className="font-medium leading-5 text-ink-700" /><ListText text={externalUser.title || "Title not provided"} lines={2} className="mt-1 text-xs text-ink-400" /></td>
                  <td className="px-4 py-3"><ListText text={externalUser.email || "—"} lines={2} className="text-xs text-ink-500" /></td>
                  <td className="px-4 py-3"><span className="block text-xs capitalize text-ink-500">{externalUser.provider}</span><ListText text={externalUser.external_id} lines={2} className="mt-1 font-mono text-[11px] text-ink-400" /></td>
                  <td className="px-4 py-3"><span className="rounded border border-linen-400 px-2 py-0.5 text-[11px] font-semibold capitalize text-ink-600">{externalUser.user_type}</span></td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          </DataTableViewport>

          <nav aria-label="External ITSM directory pagination" className="flex flex-col gap-3 rounded-xl border border-linen-400 bg-linen-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-ink-500">
              Showing <span className="font-semibold text-ink-700">{firstResult.toLocaleString()}–{lastResult.toLocaleString()}</span> of <span className="font-semibold text-ink-700">{total.toLocaleString()}</span>
            </p>
            <div className="flex items-center gap-2">
              <Button type="button" variant="secondary" size="sm" disabled={offset === 0 || directoryQuery.isFetching} onClick={() => setOffset(Math.max(0, offset - pageSize))} leadingIcon={<ChevronLeft className="h-3.5 w-3.5" />}>Previous</Button>
              <span className="min-w-16 text-center text-xs font-semibold text-ink-500">Page {Math.floor(offset / pageSize) + 1}</span>
              <Button type="button" variant="secondary" size="sm" disabled={!directory?.has_more || directoryQuery.isFetching} onClick={() => setOffset(offset + pageSize)} trailingIcon={<ChevronRight className="h-3.5 w-3.5" />}>Next</Button>
            </div>
          </nav>
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-linen-400 bg-linen-50 px-5 py-10 text-center">
          <Users className="mx-auto h-5 w-5 text-ink-400" aria-hidden="true" />
          <p className="mt-3 text-sm font-semibold text-ink-700">{hasFilters ? "No identities match this view" : "External directory is empty"}</p>
          <p className="mt-1 text-xs leading-5 text-ink-400">{hasFilters ? "Try a broader search or clear the identity filter." : "Refresh the directory to retrieve provider-owned agents and requesters."}</p>
          {hasFilters && <Button type="button" variant="secondary" size="sm" className="mt-4" onClick={clearFilters}>Clear filters</Button>}
        </div>
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
        className="group ml-3 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 disabled:cursor-not-allowed sm:h-8"
      >
        <span className={cn(
          "flex h-5 w-10 items-center rounded-full transition-colors",
          value ? "justify-end bg-moss-500" : "justify-start bg-linen-400",
        )} aria-hidden="true">
          <span className="mx-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-all" />
        </span>
      </button>
    </div>
  );
}

// ═══ Custom Status Config Section ═════════════════════════════

function ConfigColorPicker({
  name,
  value,
  onChange,
  disabled = false,
}: {
  name: string;
  value: ConfigColor;
  onChange: (value: ConfigColor) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset disabled={disabled} className="space-y-2">
      <legend className="text-sm font-medium text-ink-600">Color</legend>
      <div className="grid grid-cols-2 gap-2 xs:grid-cols-3">
        {CONFIG_COLORS.map((option) => {
          const selected = value === option.value;
          return (
            <label key={option.value} className={cn("block", disabled ? "cursor-not-allowed" : "cursor-pointer")}>
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={selected}
                onChange={() => onChange(option.value)}
                className="peer sr-only"
              />
              <span className={cn(
                "flex min-h-11 items-center gap-2 rounded-lg border px-3 text-xs font-semibold transition-colors",
                "peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-[var(--focus-ring)] peer-focus-visible:ring-offset-2",
                selected
                  ? "border-clay-300 bg-[var(--color-primary-soft)] text-ink-700"
                  : "border-linen-400 bg-linen-50 text-ink-500 hover:bg-linen-200",
              )}>
                <span className={cn("h-3 w-3 shrink-0 rounded-full", option.className)} aria-hidden="true" />
                {option.label}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function StatusConfigSection({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: ["status-config"],
    queryFn: api.getStatusConfig,
    enabled: canManage,
    retry: false,
  });
  const statuses = statusQuery.data;
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [color, setColor] = useState<ConfigColor>("slate");
  const [lifecycle, setLifecycle] = useState<StatusLifecycle>("open");
  const [formError, setFormError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<TicketStatusConfig | null>(null);

  const resetDraft = () => {
    setName("");
    setLabel("");
    setColor("slate");
    setLifecycle("open");
    setFormError(null);
  };

  const createMut = useMutation({
    mutationFn: () => api.createStatusConfig({
      name: name.trim(),
      label: label.trim(),
      color,
      is_open: lifecycle === "open",
      is_terminal: lifecycle === "terminal",
      sort_order: nextConfigSortOrder(statuses),
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["status-config"] });
      resetDraft();
      setShowForm(false);
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteStatusConfig(id),
    onSuccess: () => {
      setDeleting(null);
      void queryClient.invalidateQueries({ queryKey: ["status-config"] });
    },
    onError: () => setDeleting(null),
  });

  const normalizedName = name.trim();
  const normalizedLabel = label.trim();
  const portableName = !normalizedName || CONFIG_NAME_PATTERN.test(normalizedName);
  const duplicateName = Boolean(statuses?.some((status) => (
    status.name.trim().toLowerCase() === normalizedName.toLowerCase()
  )));
  const nextSortOrder = nextConfigSortOrder(statuses);
  const accessDenied = !canManage || [statusQuery.error, createMut.error, deleteMut.error].some(isConfigurationAccessError);
  const validationMessage = formError
    || (!portableName ? "Internal values may use letters, numbers, spaces, hyphens, and underscores." : null)
    || (duplicateName ? "A status with this internal value already exists." : null)
    || (nextSortOrder > CONFIG_SORT_ORDER_MAX ? "The status ordering limit has been reached." : null);
  const canCreate = Boolean(
    canManage
    && !accessDenied
    && normalizedName
    && normalizedLabel
    && normalizedName.length <= CONFIG_NAME_MAX_LENGTH
    && normalizedLabel.length <= CONFIG_LABEL_MAX_LENGTH
    && portableName
    && !duplicateName
    && nextSortOrder <= CONFIG_SORT_ORDER_MAX
    && !createMut.isPending
  );

  const createStatus = () => {
    if (!canCreate) {
      if (!normalizedName || !normalizedLabel) setFormError("Add both an internal value and a display label.");
      return;
    }
    setFormError(null);
    createMut.reset();
    createMut.mutate();
  };

  const retryAccess = () => {
    createMut.reset();
    deleteMut.reset();
    void statusQuery.refetch();
  };

  return (
    <>
      <SettingsSection title="Ticket statuses" subtitle="Define the ordered lifecycle choices used by ticket workflows. Internal values are stored on tickets; display labels are what people see.">
        {accessDenied ? (
          <ErrorState
            density="compact"
            title="Status configuration access could not be verified"
            description="Status values and write controls are hidden until administrator access is confirmed."
            actionLabel="Recheck access"
            onRetry={canManage ? retryAccess : undefined}
            retrying={statusQuery.isFetching}
          />
        ) : statusQuery.isLoading ? (
          <div className="space-y-2" aria-busy="true" aria-label="Loading ticket statuses">
            {[1, 2, 3].map((item) => <Skeleton key={item} className="h-12 w-full" />)}
          </div>
        ) : statusQuery.isError ? (
          <ErrorState
            density="compact"
            title="Ticket statuses could not be loaded"
            description="No lifecycle values are being shown or changed."
            actionLabel="Retry statuses"
            onRetry={() => void statusQuery.refetch()}
            retrying={statusQuery.isFetching}
          />
        ) : (
          <div className="space-y-4">
            {createMut.isError && (
              <Alert variant="danger" title="Status could not be created">
                {configErrorMessage(createMut.error, "The status was not saved.")}
              </Alert>
            )}
            {deleteMut.isError && (
              <Alert variant="danger" title="Status could not be removed">
                {configErrorMessage(deleteMut.error, "The status remains available.")}
              </Alert>
            )}

            {statuses && statuses.length > 0 ? (
              <ol className="max-h-[30rem] space-y-2 overflow-y-auto pr-1" aria-label="Configured ticket statuses">
                {statuses.map((status) => {
                  const invalidLifecycle = status.is_open && status.is_terminal;
                  const lifecycleLabel = invalidLifecycle
                    ? "Invalid lifecycle"
                    : status.is_terminal
                      ? "Terminal"
                      : status.is_open
                        ? "Open"
                        : "Inactive";
                  return (
                    <li key={status.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl border border-linen-400 bg-linen-50 px-3 py-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <span className={cn("mt-1 h-3 w-3 shrink-0 rounded-full", configColorClass(status.color))} aria-hidden="true" />
                        <div className="min-w-0">
                          <p className="break-words text-sm font-semibold text-ink-700 [overflow-wrap:anywhere]">{status.label}</p>
                          <p className="mt-0.5 break-all font-mono text-[11px] text-ink-400">{status.name}</p>
                          <span className={cn(
                            "mt-2 inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold",
                            invalidLifecycle
                              ? "border-rust-400/40 bg-[var(--color-danger-soft)] text-rust-600"
                              : status.is_open
                                ? "border-moss-500/30 bg-[var(--color-success-soft)] text-moss-600"
                                : "border-linen-400 bg-linen-200 text-ink-500",
                          )}>
                            {lifecycleLabel}
                          </span>
                        </div>
                      </div>
                      <IconButton
                        icon={<Trash2 className="h-4 w-4" />}
                        aria-label={`Remove status ${status.label}`}
                        size="sm"
                        variant="ghost"
                        onClick={() => { deleteMut.reset(); setDeleting(status); }}
                      />
                    </li>
                  );
                })}
              </ol>
            ) : (
              <div className="rounded-xl border border-dashed border-linen-400 bg-linen-50 px-4 py-6 text-center">
                <p className="text-sm font-semibold text-ink-700">No ticket statuses configured</p>
                <p className="mt-1 text-xs leading-5 text-ink-500">Add the first lifecycle value before creating or updating tickets.</p>
              </div>
            )}

            {showForm ? (
              <div
                className="space-y-4 rounded-xl border border-clay-300 bg-[var(--color-primary-soft)] p-4"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && event.target instanceof HTMLInputElement && event.target.type !== "radio") {
                    event.preventDefault();
                    createStatus();
                  }
                }}
              >
                <div>
                  <p className="text-sm font-semibold text-ink-700">Add ticket status</p>
                  <p className="mt-1 text-xs leading-5 text-ink-500">Choose one lifecycle behavior so a status can never be both open and terminal.</p>
                </div>
                <fieldset disabled={createMut.isPending} className="space-y-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <label className="block space-y-1.5" htmlFor="status-internal-value">
                      <span className="text-sm font-medium text-ink-600">Internal value</span>
                      <input
                        id="status-internal-value"
                        type="text"
                        maxLength={CONFIG_NAME_MAX_LENGTH}
                        pattern="[A-Za-z0-9][A-Za-z0-9 _-]*"
                        value={name}
                        onChange={(event) => { setName(event.target.value); setFormError(null); createMut.reset(); }}
                        placeholder="Awaiting vendor"
                        className="input-base"
                        aria-describedby="status-internal-value-help"
                      />
                      <span id="status-internal-value-help" className="block text-xs leading-5 text-ink-500">Stable ASCII key: letters, numbers, spaces, hyphens, or underscores · up to 100 characters</span>
                    </label>
                    <label className="block space-y-1.5" htmlFor="status-display-label">
                      <span className="text-sm font-medium text-ink-600">Display label</span>
                      <input
                        id="status-display-label"
                        type="text"
                        maxLength={CONFIG_LABEL_MAX_LENGTH}
                        value={label}
                        onChange={(event) => { setLabel(event.target.value); setFormError(null); createMut.reset(); }}
                        placeholder="Waiting on vendor"
                        className="input-base"
                      />
                    </label>
                  </div>

                  <fieldset className="space-y-2">
                    <legend className="text-sm font-medium text-ink-600">Lifecycle behavior</legend>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {([
                        ["open", "Open", "Counts in active ticket queues"],
                        ["terminal", "Terminal", "Closed or resolved; no longer open"],
                      ] as const).map(([value, title, description]) => (
                        <label key={value} className="cursor-pointer">
                          <input
                            type="radio"
                            name="status-lifecycle"
                            value={value}
                            checked={lifecycle === value}
                            onChange={() => setLifecycle(value)}
                            className="peer sr-only"
                          />
                          <span className={cn(
                            "block min-h-16 rounded-lg border px-3 py-2 transition-colors",
                            "peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-[var(--focus-ring)] peer-focus-visible:ring-offset-2",
                            lifecycle === value ? "border-clay-400 bg-white" : "border-linen-400 bg-linen-50 hover:bg-linen-200",
                          )}>
                            <span className="block text-sm font-semibold text-ink-700">{title}</span>
                            <span className="mt-0.5 block text-xs leading-5 text-ink-500">{description}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </fieldset>

                  <ConfigColorPicker name="status-color" value={color} onChange={setColor} disabled={createMut.isPending} />
                </fieldset>

                {validationMessage && <p role="alert" className="text-xs font-medium text-rust-600">{validationMessage}</p>}
                <div className="flex flex-col-reverse gap-2 xs:flex-row xs:justify-end">
                  <Button type="button" variant="secondary" size="sm" disabled={createMut.isPending} onClick={() => { resetDraft(); createMut.reset(); setShowForm(false); }}>Cancel</Button>
                  <Button type="button" size="sm" onClick={createStatus} disabled={!canCreate} pending={createMut.isPending} pendingLabel="Creating…" leadingIcon={<Plus className="h-4 w-4" />}>Create status</Button>
                </div>
              </div>
            ) : (
              <Button type="button" variant="secondary" size="sm" onClick={() => { resetDraft(); createMut.reset(); setShowForm(true); }} leadingIcon={<Plus className="h-4 w-4" />}>
                Add status
              </Button>
            )}
          </div>
        )}
      </SettingsSection>

      <ConfirmDialog
        open={canManage && !accessDenied && Boolean(deleting)}
        onOpenChange={(open) => { if (!open) { setDeleting(null); deleteMut.reset(); } }}
        title="Remove ticket status?"
        description={<>The option <strong>{deleting?.label}</strong> will be removed from future ticket choices. Tickets that already store this internal value are not rewritten.</>}
        confirmLabel="Remove status"
        destructive
        pending={deleteMut.isPending}
        onConfirm={() => { if (canManage && !accessDenied && deleting) deleteMut.mutate(deleting.id); }}
      />
    </>
  );
}

// ═══ Custom Priority Config Section ═══════════════════════════

function PriorityConfigSection({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const priorityQuery = useQuery({
    queryKey: ["priority-config"],
    queryFn: api.getPriorityConfig,
    enabled: canManage,
    retry: false,
  });
  const priorities = priorityQuery.data;
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [color, setColor] = useState<ConfigColor>("slate");
  const [slaHours, setSlaHours] = useState("");
  const [weight, setWeight] = useState("10");
  const [formError, setFormError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<TicketPriorityConfig | null>(null);

  const resetDraft = () => {
    setName("");
    setLabel("");
    setColor("slate");
    setSlaHours("");
    setWeight("10");
    setFormError(null);
  };

  const createMut = useMutation({
    mutationFn: () => api.createPriorityConfig({
      name: name.trim(),
      label: label.trim(),
      color,
      sla_hours: slaHours.trim() ? Number(slaHours) : null,
      weight: Number(weight),
      sort_order: nextConfigSortOrder(priorities),
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["priority-config"] });
      resetDraft();
      setShowForm(false);
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deletePriorityConfig(id),
    onSuccess: () => {
      setDeleting(null);
      void queryClient.invalidateQueries({ queryKey: ["priority-config"] });
    },
    onError: () => setDeleting(null),
  });

  const normalizedName = name.trim();
  const normalizedLabel = label.trim();
  const portableName = !normalizedName || CONFIG_NAME_PATTERN.test(normalizedName);
  const parsedSlaHours = slaHours.trim() ? Number(slaHours) : null;
  const parsedWeight = Number(weight);
  const duplicateName = Boolean(priorities?.some((priority) => (
    priority.name.trim().toLowerCase() === normalizedName.toLowerCase()
  )));
  const validSla = parsedSlaHours === null || (
    Number.isInteger(parsedSlaHours)
    && parsedSlaHours >= PRIORITY_SLA_MIN_HOURS
    && parsedSlaHours <= PRIORITY_SLA_MAX_HOURS
  );
  const validWeight = Number.isInteger(parsedWeight)
    && parsedWeight >= PRIORITY_WEIGHT_MIN
    && parsedWeight <= PRIORITY_WEIGHT_MAX;
  const nextSortOrder = nextConfigSortOrder(priorities);
  const accessDenied = !canManage || [priorityQuery.error, createMut.error, deleteMut.error].some(isConfigurationAccessError);
  const validationMessage = formError
    || (!portableName ? "Internal values may use letters, numbers, spaces, hyphens, and underscores." : null)
    || (duplicateName ? "A priority with this internal value already exists." : null)
    || (!validSla ? "SLA target must be a whole number from 1 to 8,760 hours, or left blank." : null)
    || (!validWeight ? "Queue weight must be a whole number from 1 to 1,000." : null)
    || (nextSortOrder > CONFIG_SORT_ORDER_MAX ? "The priority ordering limit has been reached." : null);
  const canCreate = Boolean(
    canManage
    && !accessDenied
    && normalizedName
    && normalizedLabel
    && normalizedName.length <= PRIORITY_NAME_MAX_LENGTH
    && normalizedLabel.length <= CONFIG_LABEL_MAX_LENGTH
    && portableName
    && !duplicateName
    && validSla
    && validWeight
    && nextSortOrder <= CONFIG_SORT_ORDER_MAX
    && !createMut.isPending
  );

  const createPriority = () => {
    if (!canCreate) {
      if (!normalizedName || !normalizedLabel) setFormError("Add both an internal value and a display label.");
      return;
    }
    setFormError(null);
    createMut.reset();
    createMut.mutate();
  };

  const retryAccess = () => {
    createMut.reset();
    deleteMut.reset();
    void priorityQuery.refetch();
  };

  return (
    <>
      <SettingsSection title="Ticket priorities" subtitle="Define ordered urgency levels for ticket workflows. Lower queue weights are treated as more urgent; an optional SLA overrides the global target.">
        {accessDenied ? (
          <ErrorState
            density="compact"
            title="Priority configuration access could not be verified"
            description="Priority values and write controls are hidden until administrator access is confirmed."
            actionLabel="Recheck access"
            onRetry={canManage ? retryAccess : undefined}
            retrying={priorityQuery.isFetching}
          />
        ) : priorityQuery.isLoading ? (
          <div className="space-y-2" aria-busy="true" aria-label="Loading ticket priorities">
            {[1, 2, 3].map((item) => <Skeleton key={item} className="h-12 w-full" />)}
          </div>
        ) : priorityQuery.isError ? (
          <ErrorState
            density="compact"
            title="Ticket priorities could not be loaded"
            description="No urgency values are being shown or changed."
            actionLabel="Retry priorities"
            onRetry={() => void priorityQuery.refetch()}
            retrying={priorityQuery.isFetching}
          />
        ) : (
          <div className="space-y-4">
            {createMut.isError && (
              <Alert variant="danger" title="Priority could not be created">
                {configErrorMessage(createMut.error, "The priority was not saved.")}
              </Alert>
            )}
            {deleteMut.isError && (
              <Alert variant="danger" title="Priority could not be removed">
                {configErrorMessage(deleteMut.error, "The priority remains available.")}
              </Alert>
            )}

            {priorities && priorities.length > 0 ? (
              <ol className="max-h-[30rem] space-y-2 overflow-y-auto pr-1" aria-label="Configured ticket priorities">
                {priorities.map((priority) => (
                  <li key={priority.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl border border-linen-400 bg-linen-50 px-3 py-3">
                    <div className="flex min-w-0 items-start gap-3">
                      <span className={cn("mt-1 h-3 w-3 shrink-0 rounded-full", configColorClass(priority.color))} aria-hidden="true" />
                      <div className="min-w-0">
                        <p className="break-words text-sm font-semibold text-ink-700 [overflow-wrap:anywhere]">{priority.label}</p>
                        <p className="mt-0.5 break-all font-mono text-[11px] text-ink-400">{priority.name}</p>
                        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] font-medium text-ink-500">
                          <span className="rounded-full border border-linen-400 bg-linen-100 px-2 py-0.5">
                            {priority.sla_hours != null ? `${priority.sla_hours}h SLA` : "Global SLA"}
                          </span>
                          <span className="rounded-full border border-linen-400 bg-linen-100 px-2 py-0.5">Queue weight {priority.weight}</span>
                        </div>
                      </div>
                    </div>
                    <IconButton
                      icon={<Trash2 className="h-4 w-4" />}
                      aria-label={`Remove priority ${priority.label}`}
                      size="sm"
                      variant="ghost"
                      onClick={() => { deleteMut.reset(); setDeleting(priority); }}
                    />
                  </li>
                ))}
              </ol>
            ) : (
              <div className="rounded-xl border border-dashed border-linen-400 bg-linen-50 px-4 py-6 text-center">
                <p className="text-sm font-semibold text-ink-700">No ticket priorities configured</p>
                <p className="mt-1 text-xs leading-5 text-ink-500">Add the first urgency value before creating or reprioritizing tickets.</p>
              </div>
            )}

            {showForm ? (
              <div
                className="space-y-4 rounded-xl border border-clay-300 bg-[var(--color-primary-soft)] p-4"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && event.target instanceof HTMLInputElement && event.target.type !== "radio") {
                    event.preventDefault();
                    createPriority();
                  }
                }}
              >
                <div>
                  <p className="text-sm font-semibold text-ink-700">Add ticket priority</p>
                  <p className="mt-1 text-xs leading-5 text-ink-500">Use a lower queue weight for work that should rank ahead of less urgent tickets.</p>
                </div>
                <fieldset disabled={createMut.isPending} className="space-y-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <label className="block space-y-1.5" htmlFor="priority-internal-value">
                      <span className="text-sm font-medium text-ink-600">Internal value</span>
                      <input
                        id="priority-internal-value"
                        type="text"
                        maxLength={PRIORITY_NAME_MAX_LENGTH}
                        pattern="[A-Za-z0-9][A-Za-z0-9 _-]*"
                        value={name}
                        onChange={(event) => { setName(event.target.value); setFormError(null); createMut.reset(); }}
                        placeholder="P5"
                        className="input-base"
                        aria-describedby="priority-internal-value-help"
                      />
                      <span id="priority-internal-value-help" className="block text-xs leading-5 text-ink-500">Stable ASCII key: letters, numbers, spaces, hyphens, or underscores · up to 32 characters</span>
                    </label>
                    <label className="block space-y-1.5" htmlFor="priority-display-label">
                      <span className="text-sm font-medium text-ink-600">Display label</span>
                      <input
                        id="priority-display-label"
                        type="text"
                        maxLength={CONFIG_LABEL_MAX_LENGTH}
                        value={label}
                        onChange={(event) => { setLabel(event.target.value); setFormError(null); createMut.reset(); }}
                        placeholder="Planning"
                        className="input-base"
                      />
                    </label>
                  </div>

                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <label className="block space-y-1.5" htmlFor="priority-sla-hours">
                      <span className="text-sm font-medium text-ink-600">SLA target <span className="font-normal text-ink-400">(optional)</span></span>
                      <div className="relative">
                        <input
                          id="priority-sla-hours"
                          type="number"
                          min={PRIORITY_SLA_MIN_HOURS}
                          max={PRIORITY_SLA_MAX_HOURS}
                          step={1}
                          inputMode="numeric"
                          value={slaHours}
                          onChange={(event) => { setSlaHours(event.target.value); setFormError(null); createMut.reset(); }}
                          placeholder="Uses global target"
                          className="input-base pr-16"
                          aria-describedby="priority-sla-hours-help"
                        />
                        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-400">hours</span>
                      </div>
                      <span id="priority-sla-hours-help" className="block text-xs leading-5 text-ink-500">1–8,760; leave blank to use the global SLA</span>
                    </label>
                    <label className="block space-y-1.5" htmlFor="priority-queue-weight">
                      <span className="text-sm font-medium text-ink-600">Queue weight</span>
                      <input
                        id="priority-queue-weight"
                        type="number"
                        min={PRIORITY_WEIGHT_MIN}
                        max={PRIORITY_WEIGHT_MAX}
                        step={1}
                        inputMode="numeric"
                        value={weight}
                        onChange={(event) => { setWeight(event.target.value); setFormError(null); createMut.reset(); }}
                        className="input-base"
                        aria-describedby="priority-queue-weight-help"
                      />
                      <span id="priority-queue-weight-help" className="block text-xs leading-5 text-ink-500">1–1,000 · lower values rank as more urgent</span>
                    </label>
                  </div>

                  <ConfigColorPicker name="priority-color" value={color} onChange={setColor} disabled={createMut.isPending} />
                </fieldset>

                {validationMessage && <p role="alert" className="text-xs font-medium text-rust-600">{validationMessage}</p>}
                <div className="flex flex-col-reverse gap-2 xs:flex-row xs:justify-end">
                  <Button type="button" variant="secondary" size="sm" disabled={createMut.isPending} onClick={() => { resetDraft(); createMut.reset(); setShowForm(false); }}>Cancel</Button>
                  <Button type="button" size="sm" onClick={createPriority} disabled={!canCreate} pending={createMut.isPending} pendingLabel="Creating…" leadingIcon={<Plus className="h-4 w-4" />}>Create priority</Button>
                </div>
              </div>
            ) : (
              <Button type="button" variant="secondary" size="sm" onClick={() => { resetDraft(); createMut.reset(); setShowForm(true); }} leadingIcon={<Plus className="h-4 w-4" />}>
                Add priority
              </Button>
            )}
          </div>
        )}
      </SettingsSection>

      <ConfirmDialog
        open={canManage && !accessDenied && Boolean(deleting)}
        onOpenChange={(open) => { if (!open) { setDeleting(null); deleteMut.reset(); } }}
        title="Remove ticket priority?"
        description={<>The option <strong>{deleting?.label}</strong> will be removed from future ticket choices. Tickets that already store this internal value are not rewritten.</>}
        confirmLabel="Remove priority"
        destructive
        pending={deleteMut.isPending}
        onConfirm={() => { if (canManage && !accessDenied && deleting) deleteMut.mutate(deleting.id); }}
      />
    </>
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
                role="switch"
                aria-checked={n.enabled}
                aria-label={`${n.label} notifications`}
                disabled={updateMut.isPending}
                onClick={() => updateMut.mutate({ event: n.event, enabled: !n.enabled, channels: n.channels })}
                className="group inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:h-8"
              >
                <span className={cn(
                  "flex h-5 w-10 items-center rounded-full transition-colors",
                  n.enabled ? "justify-end bg-moss-500" : "justify-start bg-linen-400",
                )} aria-hidden="true">
                  <span className="mx-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-all" />
                </span>
              </button>
            </div>
          ))}
        </div>
      )}
    </SettingsSection>
  );
}
