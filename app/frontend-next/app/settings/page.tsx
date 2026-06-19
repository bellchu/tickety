"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Settings as SettingsType, LlmCatalog, LlmProvider } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Settings as SettingsIcon, Save, RefreshCw, CheckCircle2, AlertCircle, Users, Download } from "lucide-react";
import { SearchableSelect } from "@/components/ui/SearchableSelect";

const PROVIDER_OPTIONS = [
  { value: "freshservice", label: "Freshservice" },
];

// Provider ids rendered in the dropdown (drives which models/keys show).
const PROVIDER_IDS = ["deepseek", "openai", "openrouter", "azure", "azure_ai"] as const;

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
  });
  const { data: catalog } = useQuery({
    queryKey: ["llm-catalog"],
    queryFn: api.getLlmCatalog,
  });

  const [form, setForm] = useState<Partial<SettingsType>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const mutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (result) => {
      setForm(result);
      setSaved(true);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      queryClient.invalidateQueries({ queryKey: ["llm-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      setTimeout(() => setSaved(false), 2500);
    },
  });

  // Live model refresh
  const [fetchedInfo, setFetchedInfo] = useState<{ total_models: number; providers_queried: string[] } | null>(null);
  const refreshMut = useMutation({
    mutationFn: api.refreshModels,
    onSuccess: (res) => {
      setFetchedInfo({ total_models: res.total_models, providers_queried: res.providers_queried });
      queryClient.invalidateQueries({ queryKey: ["llm-catalog"] });
      // Re-read the catalog now that models are refreshed
      queryClient.fetchQuery({ queryKey: ["llm-catalog"], queryFn: api.getLlmCatalog });
    },
  });

  const handleChange = (key: keyof SettingsType, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  // Resolve the active provider from the current DEFAULT_MODEL value.
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

  const activeProvider: LlmProvider | undefined = catalog
    ? (catalog[activeProviderId] as LlmProvider)
    : undefined;

  const handleProviderChange = (pid: string) => {
    const prov = catalog ? (catalog[pid] as LlmProvider) : undefined;
    if (!prov) return;
    // Pick the first preset model, or fall back to the model hint prefix.
    const firstModel =
      prov.models[0]?.id || (prov.model_hint ? prov.model_hint : "");
    handleChange("DEFAULT_MODEL", firstModel);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload: Record<string, string> = {};
    for (const key of Object.keys(form)) {
      const v = form[key as keyof SettingsType];
      if (typeof v !== "string" || v === "") continue;
      // Never send back the masked echo (e.g. "sk-5****") for secret fields —
      // it's the redacted value returned by GET, not a real key. Skipping it
      // keeps the previously stored key intact.
      if (v.includes("****")) continue;
      payload[key] = v;
    }
    mutation.mutate(payload);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-400">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading settings…
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-3xl">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center">
          <SettingsIcon className="w-5 h-5 text-slate-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Settings</h1>
          <p className="text-sm text-slate-500">Configure ITSM integration and LLM model</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* LLM Section */}
        <section className="card-surface p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">LLM Model</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Choose the provider and model used for ticket triage and replies.
            </p>
          </div>
          <Field label="Provider">
            <select
              value={activeProviderId}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="input-base"
            >
              {PROVIDER_IDS.map((pid) => (
                <option key={pid} value={pid}>
                  {catalog ? (catalog[pid] as LlmProvider)?.label ?? pid : pid}
                </option>
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
              <input
                type="text"
                value={form.DEFAULT_MODEL || ""}
                onChange={(e) => handleChange("DEFAULT_MODEL", e.target.value)}
                placeholder={activeProvider?.model_hint || "model id"}
                className="input-base"
              />
            )}
          </Field>

          {/* Refresh live models from providers */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">
              {fetchedInfo
                ? `Last fetch: ${fetchedInfo.total_models} models from ${fetchedInfo.providers_queried.length} providers`
                : "Model list shows built‑in defaults + any previously fetched models."}
            </span>
            <button
              type="button"
              onClick={() => refreshMut.mutate()}
              disabled={refreshMut.isPending}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              {refreshMut.isPending ? (
                <RefreshCw className="w-3 h-3 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
              {refreshMut.isPending ? "Fetching…" : "Fetch Latest Models"}
            </button>
          </div>

          {/* Provider-specific credentials (driven by the catalog). */}
          {activeProvider?.env_keys.map((ek) => (
            <Field key={ek.key} label={`${ek.label}${ek.is_set ? " ✓" : ""}`}>
              {ek.secret ? (
                <SecretInput
                  value={(form[ek.key as keyof SettingsType] as string) || ""}
                  onChange={(v) => handleChange(ek.key as keyof SettingsType, v)}
                  placeholder={ek.placeholder}
                />
              ) : (
                <input
                  type="text"
                  value={(form[ek.key as keyof SettingsType] as string) || ""}
                  onChange={(e) =>
                    handleChange(ek.key as keyof SettingsType, e.target.value)
                  }
                  placeholder={ek.placeholder}
                  className="input-base"
                />
              )}
            </Field>
          ))}
        </section>

        {/* ITSM Section */}
        <section className="card-surface p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">ITSM Integration</h2>
            <p className="text-xs text-slate-500 mt-0.5">Connect an external ITSM system to sync tickets.</p>
          </div>
          <Field label="Provider">
            <select
              value={form.ITSM_PROVIDER || ""}
              onChange={(e) => handleChange("ITSM_PROVIDER", e.target.value)}
              className="input-base"
            >
              {PROVIDER_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Freshservice Domain">
            <input
              type="text"
              value={form.FRESHSERVICE_DOMAIN || ""}
              onChange={(e) => handleChange("FRESHSERVICE_DOMAIN", e.target.value)}
              placeholder="yourdomain.freshservice.com"
              className="input-base"
            />
          </Field>
          <Field label="Freshservice API Key">
            <SecretInput
              value={form.FRESHSERVICE_API_KEY || ""}
              onChange={(v) => handleChange("FRESHSERVICE_API_KEY", v)}
              placeholder="Freshservice API key"
            />
          </Field>
          <Field label="Webhook Secret">
            <SecretInput
              value={form.WEBHOOK_SECRET || ""}
              onChange={(v) => handleChange("WEBHOOK_SECRET", v)}
              placeholder="Webhook shared secret"
            />
          </Field>
          <Field label="Sync Interval (seconds)">
            <input
              type="number"
              min={10}
              value={form.SYNC_INTERVAL_SECONDS || ""}
              onChange={(e) => handleChange("SYNC_INTERVAL_SECONDS", e.target.value)}
              placeholder="60"
              className="input-base"
            />
          </Field>

          <div className="border-t border-slate-100 pt-4 mt-2">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">SLA Targets (hours)</p>
            <div className="grid grid-cols-3 gap-3">
              {[
                ["SLA_P1_HOURS", "P1 (Critical)"],
                ["SLA_P2_HOURS", "P2 (High)"],
                ["SLA_P3_HOURS", "P3 (Normal)"],
              ].map(([key, label]) => {
                const defaults: Record<string, string> = {"SLA_P1_HOURS":"4", "SLA_P2_HOURS":"24", "SLA_P3_HOURS":"72"};
                return (
                <label key={key} className="block space-y-1">
                  <span className="text-[11px] text-slate-500">{label}</span>
                  <input
                    type="number"
                    min={1}
                    max={720}
                    value={(form[key as keyof SettingsType] as string) || defaults[key] || ""}
                    onChange={(e) => handleChange(key as keyof SettingsType, e.target.value)}
                    placeholder={defaults[key]}
                    className="input-base"
                  />
                  <span className="text-[10px] text-slate-400">hours</span>
                </label>
              );})}
            </div>
          </div>
        </section>

        {/* AI Automation Section */}


        {/* OAuth 2.0 Section */}
        <OAuthSection form={form} onChange={handleChange} />

        {/* Agent Management Section */}
        <AgentSection />

        {/* Save Bar */}
        <div className="flex items-center justify-end gap-3">
          {saved && (
            <span className="flex items-center gap-1.5 text-sm text-slate-600">
              <CheckCircle2 className="w-4 h-4" /> Saved
            </span>
          )}
          {mutation.isError && (
            <span className="flex items-center gap-1.5 text-sm text-red-600">
              <AlertCircle className="w-4 h-4" /> Failed to save
            </span>
          )}
          <button
            type="submit"
            disabled={mutation.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 text-white text-sm font-medium hover:bg-slate-700 disabled:opacity-50 transition-colors"
          >
            {mutation.isPending ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            Save Changes
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}

function SecretInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [reveal, setReveal] = useState(false);
  const isMasked = value.includes("****");
  return (
    <div className="flex gap-2">
      <input
        type={reveal ? "text" : "password"}
        value={isMasked ? "" : value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={isMasked ? "•••• stored, type to replace" : placeholder}
        onFocus={() => {
          if (isMasked) onChange("");
        }}
        className="input-base flex-1"
      />
      <button
        type="button"
        onClick={() => setReveal((r) => !r)}
        className="px-3 rounded-lg border border-slate-200 text-xs text-slate-500 hover:bg-slate-50"
      >
        {reveal ? "Hide" : "Show"}
      </button>
    </div>
  );
}
// ── Agent Management Section ──────────────────────────────────

function AgentSection() {
  const queryClient = useQueryClient();

  const { data: agentList, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: api.getAgents,
  });

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
    <section className="card-surface p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Agent Accounts</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Sync agents from your ITSM provider to create Tickety accounts for
            point tracking and leaderboard participation.
          </p>
        </div>
        <button
          onClick={() => syncMut.mutate()}
          disabled={syncMut.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 text-white text-sm font-medium hover:bg-slate-700 disabled:opacity-50 transition-colors"
        >
          {syncMut.isPending ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" /> Syncing…
            </>
          ) : (
            <>
              <Download className="w-4 h-4" /> Fetch Agents
            </>
          )}
        </button>
      </div>

      {/* Sync result */}
      {syncMut.isSuccess && syncMut.data && (
        <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm">
          <span className="font-medium text-slate-700">Sync complete:</span>{" "}
          {syncMut.data.result.total} fetched,{" "}
          {syncMut.data.result.skipped_inactive > 0 && (
            <>{syncMut.data.result.skipped_inactive} <span className="text-slate-500">inactive skipped</span>,{" "}</>
          )}
          <span className="text-slate-700 font-medium">{syncMut.data.result.created} created</span>
          {syncMut.data.result.updated > 0 && (
            <>, <span className="text-slate-600">{syncMut.data.result.updated} updated</span></>
          )}
          {syncMut.data.result.errors > 0 && (
            <>, <span className="text-red-600 font-medium">{syncMut.data.result.errors} errors</span></>
          )}
        </div>
      )}

      {syncMut.isError && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Sync failed: {syncMut.error instanceof Error ? syncMut.error.message : "Unknown error"}
        </div>
      )}

      {/* Agent table */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton h-10 w-full" />
          ))}
        </div>
      ) : agents.length > 0 ? (
        <div className="overflow-hidden rounded border border-slate-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Name</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Email</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Title</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">Points</th>
                <th className="px-4 py-2.5 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">Tier</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-2.5 font-medium text-slate-900">{a.name}</td>
                  <td className="px-4 py-2.5 text-slate-500">{a.email || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-500">{a.title || "—"}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums font-medium text-slate-700">{a.impact_points.toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-center">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border border-slate-200 text-slate-600">
                      T{a.tier}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-slate-400 py-2">
          {syncMut.isSuccess
            ? "No agents found in the ITSM provider."
            : "Click &ldquo;Fetch Agents&rdquo; to sync agent accounts from your ITSM provider."}
        </p>
      )}
    </section>
  );
}

// ── OAuth 2.0 Section ────────────────────────────────────────

function OAuthSection({ form, onChange }: { form: Partial<SettingsType>; onChange: (key: keyof SettingsType, value: string) => void }) {
  const queryClient = useQueryClient();

  const { data: status } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: api.getOAuthStatus,
    refetchInterval: 30000,
  });

  const authMut = useMutation({
    mutationFn: api.getOAuthAuthorizeUrl,
    onSuccess: (res) => {
      window.open(res.url, "_blank", "width=700,height=600");
    },
  });

  return (
    <section className="card-surface p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Freshservice OAuth 2.0</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Authenticate via OAuth (recommended by Freshworks App SDK). Once
            connected, the API key field below is ignored.
          </p>
        </div>
        {status?.connected ? (
          <span className="inline-flex items-center gap-1.5 rounded border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600">
            <CheckCircle2 className="w-3.5 h-3.5" /> Connected to {status.domain}
          </span>
        ) : (
          <button
            onClick={() => authMut.mutate()}
            disabled={authMut.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 text-white text-sm font-medium hover:bg-slate-700 disabled:opacity-50 transition-colors"
          >
            {authMut.isPending ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <CheckCircle2 className="w-4 h-4" />
            )}
            Authorize with Freshservice
          </button>
        )}
      </div>

      {authMut.isError && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {authMut.error instanceof Error ? authMut.error.message : "Failed to get authorization URL"}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="OAuth Client ID">
          <SecretInput
            value={form["FRESHSERVICE_OAUTH_CLIENT_ID"] || ""}
            onChange={(v) => onChange("FRESHSERVICE_OAUTH_CLIENT_ID", v)}
            placeholder="From Freshworks Developer Portal"
          />
        </Field>
        <Field label="OAuth Client Secret">
          <SecretInput
            value={form["FRESHSERVICE_OAUTH_CLIENT_SECRET"] || ""}
            onChange={(v) => onChange("FRESHSERVICE_OAUTH_CLIENT_SECRET", v)}
            placeholder="Client secret"
          />
        </Field>
      </div>
      <Field label="Redirect URI (must match Freshworks app config)">
        <input
          type="text"
          value={form["FRESHSERVICE_OAUTH_REDIRECT_URI"] || ""}
          onChange={(e) => onChange("FRESHSERVICE_OAUTH_REDIRECT_URI", e.target.value)}
          placeholder="http://localhost:8000/oauth/callback"
          className="input-base"
        />
      </Field>
      <p className="text-[11px] text-slate-400">
        After authorising, copy the <code className="font-mono text-slate-500">?code=…</code> parameter
        from the callback URL and paste it into the field below, then save.
      </p>
    </section>
  );
}

// ── AI Automation Section ─────────────────────────────────────

