import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Use a same-origin "/api" base so the browser calls the Next.js server,
// which proxies to the backend via rewrites in next.config.js. This avoids
// needing the browser to reach the in-cluster backend directly (it can't).
const API_PREFIX = "/api";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : ({} as T);
}

export const api = {
  getTickets: () => fetchAPI<import("./types").Ticket[]>("/tickets"),
  createTicket: (payload: import("./types").TicketCreateInput) =>
    fetchAPI<import("./types").Ticket>("/tickets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getTicket: (id: string) => fetchAPI<import("./types").Ticket>(`/tickets/${id}`),
  triggerTriage: (id: string) =>
    fetchAPI<import("./types").TriageResult>(`/tickets/${id}/triage`, { method: "POST" }),
  getMe: () => fetchAPI<import("./types").User>("/me"),
  getUser: (id: string) => fetchAPI<import("./types").User>(`/users/${id}`),
  getLeaderboard: () => fetchAPI<import("./types").UserSummary[]>("/leaderboard"),
  getRecognitions: (userId: string) =>
    fetchAPI<import("./types").Recognition[]>(`/recognitions/${userId}`),
  getSyncStatus: () => fetchAPI<import("./types").SyncStatus>("/admin/sync/status"),
  triggerSync: () => fetchAPI<{ status: string; result: Record<string, number> }>("/admin/sync/trigger", { method: "POST" }),
  fetchTickets: (days: number, overwrite = false) =>
    fetchAPI<{ status: string; result: import("./types").FetchTicketsResult }>(
      `/admin/sync/fetch?days=${days}&overwrite=${overwrite ? 1 : 0}`,
      { method: "POST" }
    ),
  syncAgents: () =>
    fetchAPI<{ status: string; result: import("./types").SyncAgentsResult }>(
      "/admin/sync/agents", { method: "POST" }
    ),
  getAgents: () => fetchAPI<import("./types").AgentListResponse>("/admin/agents"),
  // OAuth 2.0
  getOAuthStatus: () => fetchAPI<{ configured: boolean; connected: boolean; domain: string }>("/oauth/status"),
  getOAuthAuthorizeUrl: () => fetchAPI<{ url: string }>("/oauth/authorize"),
  getSettings: () => fetchAPI<import("./types").Settings>("/admin/settings"),
  updateSettings: (payload: Partial<import("./types").Settings>) =>
    fetchAPI<import("./types").Settings>("/admin/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  getLlmCatalog: () => fetchAPI<import("./types").LlmCatalog>("/admin/llm/catalog"),
  refreshModels: () =>
    fetchAPI<{ status: string; providers_queried: string[]; total_models: number; results: Record<string, number> }>(
      "/admin/llm/refresh-models", { method: "POST" }
    ),
  // Intelligence agents
  getIntelAlerts: () => fetchAPI<import("./types").IntelAlertsResponse>("/intelligence/alerts"),
  getIntelPrioritize: () =>
    fetchAPI<import("./types").IntelPrioritizeResponse>("/intelligence/prioritize"),
  getIntelSla: () => fetchAPI<import("./types").IntelSlaResponse>("/intelligence/sla"),
  getIntelTrends: () => fetchAPI<import("./types").IntelTrendsResponse>("/intelligence/trends"),
  getIntelSystemic: (minCluster = 2) =>
    fetchAPI<import("./types").SystemicIssuesResponse>(
      `/intelligence/systemic?min_cluster=${minCluster}`
    ),
  getIntelHealth: (reporter: string) =>
    fetchAPI<import("./types").AccountHealth>(`/intelligence/health/${encodeURIComponent(reporter)}`),
  getIntelRoute: (ticketId: string) =>
    fetchAPI<import("./types").RouteRecommendation>(`/intelligence/route/${ticketId}`),
  generateTicketSummary: (ticketId: string) =>
    fetchAPI<import("./types").TicketSummary>(`/tickets/${ticketId}/summary`, { method: "POST" }),
  getRecommendedSolution: (ticketId: string, force = false) =>
    fetchAPI<import("./types").RecommendedSolution>(
      `/intelligence/resolve/${ticketId}?force=${force ? 1 : 0}`,
      { method: "POST" }
    ),
  getVersion: () => fetchAPI<import("./types").BuildInfo>("/version"),
};