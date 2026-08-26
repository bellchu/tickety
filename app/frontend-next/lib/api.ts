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

export class APIError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "APIError";
  }
}

function redirectExpiredSessionToLogin(path: string, status: number) {
  if (status !== 401 || typeof window === "undefined" || path.startsWith("/auth/")) return;
  const currentPath = `${window.location.pathname}${window.location.search}`;
  if (currentPath.startsWith("/login") || currentPath.startsWith("/portal")) return;
  window.location.replace(`/login?next=${encodeURIComponent(currentPath)}`);
}

async function fetchAPIResponse<T>(path: string, options?: RequestInit): Promise<{ data: T; response: Response }> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    credentials: "include",
    cache: "no-store",
  });
  const text = await res.text();
  if (!res.ok) {
    let detail = `API ${path} failed: ${res.status}`;
    if (text) {
      try {
        const data = JSON.parse(text);
        if (typeof data.detail === "string") detail = data.detail;
      } catch {
        detail = text;
      }
    }
    redirectExpiredSessionToLogin(path, res.status);
    throw new APIError(detail, res.status);
  }
  return { data: text ? JSON.parse(text) : ({} as T), response: res };
}

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  return (await fetchAPIResponse<T>(path, options)).data;
}

const API_RESOLVER_GROUPS = new Set([
  "INFRA_HELPDESK", "INFRA_NETWORK", "INFRA_SYSTEMS", "INFRA_ARCH",
  "APP_CRM_ALMO", "APP_CRM_JAM", "APP_RPA", "APP_SQL", "APP_JDE",
  "APP_JDE_BA", "APP_KORBER", "APP_AS400", "APP_WEB", "APP_EDI_API",
  "APP_PM",
]);
const ROUTE_LINE_BREAKS = [
  "\n", "\r", "\v", "\f", "\u001c", "\u001d", "\u001e", "\u0085", "\u2028", "\u2029",
];

function isResolverRouteText(value: unknown, maxLength: number): value is string {
  return typeof value === "string"
    && value.length > 0
    && value.length <= maxLength
    && value === value.trim()
    && !ROUTE_LINE_BREAKS.some((separator) => value.includes(separator));
}

function isResolverRouteResponse(value: unknown): value is import("./types").RouteRecommendation {
  if (typeof value !== "object" || value === null) return false;
  const route = value as Record<string, unknown>;
  const exactKeys = [
    "primary_group", "secondary_group", "confidence", "business_context",
    "scope", "affected_service", "failure_domain", "reason",
  ];
  const unknownEvidence = [route.affected_service, route.failure_domain].some(
    (item) => typeof item === "string" && item.toLowerCase() === "unknown",
  );
  const selectedGroups = [route.primary_group, route.secondary_group];
  return Object.keys(route).length === exactKeys.length
    && exactKeys.every((key) => Object.prototype.hasOwnProperty.call(route, key))
    && typeof route.primary_group === "string"
    && API_RESOLVER_GROUPS.has(route.primary_group)
    && (route.secondary_group === null || (
      typeof route.secondary_group === "string"
      && API_RESOLVER_GROUPS.has(route.secondary_group)
    ))
    && route.secondary_group !== route.primary_group
    && route.secondary_group !== "INFRA_HELPDESK"
    && typeof route.confidence === "number"
    && Number.isFinite(route.confidence)
    && route.confidence >= 0
    && route.confidence <= 1
    && (!unknownEvidence || route.confidence < 0.60)
    && ["ALMO", "JAM", "UNKNOWN"].includes(String(route.business_context))
    && (!selectedGroups.includes("APP_CRM_ALMO") || route.business_context === "ALMO")
    && (!selectedGroups.includes("APP_CRM_JAM") || route.business_context === "JAM")
    && ["single_user", "multiple_users", "service_wide", "unknown"].includes(String(route.scope))
    && isResolverRouteText(route.affected_service, 255)
    && isResolverRouteText(route.failure_domain, 255)
    && isResolverRouteText(route.reason, 1_000);
}

async function fetchResolverRoute(path: string, options?: RequestInit) {
  const data = await fetchAPI<unknown>(path, options);
  if (!isResolverRouteResponse(data)) {
    throw new APIError("Invalid resolver routing response", 502);
  }
  return data;
}

function reportPath(path: string, filters: import("./types").ReportFilters): string {
  const params = new URLSearchParams({
    start_at: filters.startAt,
    end_at: filters.endAt,
    date_field: filters.dateField,
  });
  if (filters.status) params.set("status", filters.status);
  if (filters.priority) params.set("priority", filters.priority);
  if (filters.category) params.set("category", filters.category);
  if (filters.assigneeId) params.set("assignee_id", filters.assigneeId);
  if (filters.source) params.set("source", filters.source);
  if (filters.ticketType) params.set("ticket_type", filters.ticketType);
  if (filters.resolutionState) params.set("resolution_state", filters.resolutionState);
  if (filters.slaState) params.set("sla_state", filters.slaState);
  return `${path}?${params.toString()}`;
}

async function downloadReportCsv(filters: import("./types").ReportFilters) {
  const path = reportPath("/reports/export", filters);
  const response = await fetch(`${API_PREFIX}${path}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = `API ${path} failed: ${response.status}`;
    if (text) {
      try {
        const data = JSON.parse(text);
        if (typeof data.detail === "string") detail = data.detail;
      } catch {
        detail = text;
      }
    }
    redirectExpiredSessionToLogin(path, response.status);
    throw new APIError(detail, response.status);
  }
  const disposition = response.headers.get("content-disposition") || "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
    || "tickety-ticket-report.csv";
  return {
    blob: await response.blob(),
    filename,
    rowCount: Number(response.headers.get("x-report-rows")) || 0,
  };
}

export const api = {
  getHealth: () => fetchAPI<{ status: string; mode: "demo" | "production" }>("/health"),
  getReadiness: () => fetchAPI<import("./types").ReadinessStatus>("/health/ready"),
  getTickets: () => fetchAPI<import("./types").Ticket[]>("/tickets"),
  getDashboardSummary: () =>
    fetchAPI<import("./types").DashboardSummary>("/dashboard/summary"),
  getAgentWorkspaceBootstrap: () =>
    fetchAPI<import("./types").AgentWorkspaceBootstrap>("/agent-workspace/bootstrap"),
  getAgentWorkspaceTickets: async (
    options: import("./types").AgentWorkspaceTicketParams = {},
  ) => {
    const params = new URLSearchParams();
    if (options.scope) params.set("scope", options.scope);
    if (options.teamId) params.set("team_id", options.teamId);
    if (options.ticketId) params.set("ticket_id", options.ticketId);
    if (options.folder) params.set("folder", options.folder);
    if (options.search?.trim()) params.set("search", options.search.trim());
    if (options.limit != null) params.set("limit", String(options.limit));
    if (options.offset != null) params.set("offset", String(options.offset));
    const path = `/agent-workspace/tickets${params.size ? `?${params.toString()}` : ""}`;
    const { data, response } = await fetchAPIResponse<import("./types").AgentWorkspaceTicket[]>(path);
    return {
      tickets: data,
      hasMore: response.headers.get("x-has-more") === "true",
    };
  },
  updateAgentTicketState: (
    ticketId: string,
    payload: import("./types").AgentTicketStateUpdate,
  ) => fetchAPI<{
    ticket_id: string;
    last_seen_at: string | null;
    starred_at: string | null;
    follow_up_at: string | null;
  }>(`/agent-workspace/tickets/${encodeURIComponent(ticketId)}/state`, {
    method: "PUT",
    body: JSON.stringify(payload),
  }),
  getTicketsPage: async (options: import("./types").TicketListParams = {}) => {
    const params = new URLSearchParams();
    if (options.status) params.set("status", options.status);
    if (options.priority) params.set("priority", options.priority);
    if (options.assigneeId) params.set("assignee_id", options.assigneeId);
    if (options.category) params.set("category", options.category);
    if (options.search) params.set("search", options.search);
    if (options.sort) params.set("sort", options.sort);
    if (options.limit != null) params.set("limit", String(options.limit));
    if (options.offset != null) params.set("offset", String(options.offset));
    const path = `/tickets${params.size ? `?${params.toString()}` : ""}`;
    const { data, response } = await fetchAPIResponse<import("./types").Ticket[]>(path);
    return {
      tickets: data,
      limit: Number(response.headers.get("x-page-limit")) || options.limit || 100,
      offset: Number(response.headers.get("x-page-offset")) || options.offset || 0,
      hasMore: response.headers.get("x-has-more") === "true",
    } satisfies import("./types").TicketPage;
  },
  createTicket: (payload: import("./types").TicketCreateInput) =>
    fetchAPI<import("./types").Ticket>("/tickets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getTicket: (id: string) => fetchAPI<import("./types").Ticket>(`/tickets/${id}`),
  getRelatedTickets: (id: string, limit = 5) =>
    fetchAPI<import("./types").RelatedTicketsResponse>(`/tickets/${id}/related?limit=${limit}`),
  triggerTriage: (id: string) =>
    fetchAPI<import("./types").TriageResult>(`/tickets/${id}/triage`, { method: "POST" }),
  runTicketAnalysis: (id: string) =>
    fetchAPI<import("./types").TicketAnalysisResult>(`/tickets/${id}/analysis`, { method: "POST" }),
  getMe: () => fetchAPI<import("./types").User>("/me"),
  getUser: (id: string) => fetchAPI<import("./types").User>(`/users/${id}`),
  getLeaderboard: () => fetchAPI<import("./types").UserSummary[]>("/leaderboard"),
  getRecognitions: (userId: string) =>
    fetchAPI<import("./types").Recognition[]>(`/recognitions/${userId}`),
  getSyncStatus: () => fetchAPI<import("./types").SyncStatus>("/admin/sync/status"),
  triggerSync: () => fetchAPI<{ status: string; result: Record<string, number> }>("/admin/sync/trigger", { method: "POST" }),
  fetchOldTickets: (request: {
    preset: "2_months" | "3_months" | "custom";
    startDate?: string;
    endDate?: string;
  }) => {
    const params = new URLSearchParams({ preset: request.preset });
    if (request.startDate) params.set("start_date", request.startDate);
    if (request.endDate) params.set("end_date", request.endDate);
    return fetchAPI<{
      status: string;
      result: import("./types").FetchOldTicketsResult;
    }>(`/admin/sync/fetch?${params.toString()}`, { method: "POST" });
  },
  syncExternalUsers: () =>
    fetchAPI<{ status: string; result: import("./types").ExternalUserSyncResult }>(
      "/admin/sync/external-users", { method: "POST" }
    ),
  getExternalUsers: (options: import("./types").ExternalUserListParams = {}) => {
    const params = new URLSearchParams();
    if (options.search?.trim()) params.set("search", options.search.trim());
    if (options.userType) params.set("user_type", options.userType);
    if (options.limit != null) params.set("limit", String(options.limit));
    if (options.offset != null) params.set("offset", String(options.offset));
    return fetchAPI<import("./types").ExternalUserListResponse>(
      `/admin/external-users${params.size ? `?${params.toString()}` : ""}`
    );
  },
  getAgentIdentityLinks: (userId?: string) => {
    const params = new URLSearchParams();
    if (userId) params.set("user_id", userId);
    return fetchAPI<import("./types").UserExternalIdentityLink[]>(
      `/admin/agent-identity-links${params.size ? `?${params.toString()}` : ""}`
    );
  },
  setAgentIdentityLink: (userId: string, externalUserId: string) =>
    fetchAPI<import("./types").UserExternalIdentityLink>(
      `/admin/agent-identity-links/${encodeURIComponent(userId)}`,
      { method: "PUT", body: JSON.stringify({ external_user_id: externalUserId }) },
    ),
  deleteAgentIdentityLink: (userId: string, linkId: number) =>
    fetchAPI<{ status: string; user_id: string; link_id: number }>(
      `/admin/agent-identity-links/${encodeURIComponent(userId)}/${linkId}`,
      { method: "DELETE" },
    ),
  getEmailStatus: () =>
    fetchAPI<import("./types").EmailProviderStatus>("/email/status"),
  getEmailRecipients: (audience: import("./types").EmailAudience, search = "") => {
    const params = new URLSearchParams({ audience, limit: "100" });
    if (search.trim()) params.set("search", search.trim());
    return fetchAPI<import("./types").EmailRecipientList>(
      `/email/recipients?${params.toString()}`
    );
  },
  sendEmail: (payload: import("./types").EmailSendInput) =>
    fetchAPI<import("./types").EmailSendResponse>("/email/send", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  // OAuth 2.0
  getOAuthStatus: () => fetchAPI<{ configured: boolean; connected: boolean; domain: string }>("/oauth/status"),
  getOAuthAuthorizeUrl: () => fetchAPI<{ url: string }>("/oauth/authorize"),
  getSettings: () => fetchAPI<import("./types").Settings>("/admin/settings"),
  getAIStatus: (options: {
    view?: import("./types").AITaskView;
    search?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const params = new URLSearchParams();
    if (options.view) params.set("view", options.view);
    if (options.search) params.set("search", options.search);
    if (options.limit != null) params.set("limit", String(options.limit));
    if (options.offset != null) params.set("offset", String(options.offset));
    return fetchAPI<import("./types").AIStatusResponse>(
      `/admin/settings/ai-status${params.size ? `?${params.toString()}` : ""}`
    );
  },
  clearScheduledAIRetries: () =>
    fetchAPI<import("./types").AIRetryQueueActionResponse>(
      "/admin/settings/ai-status/retries/clear",
      { method: "POST" },
    ),
  retryAllScheduledAINow: () =>
    fetchAPI<import("./types").AIRetryQueueActionResponse>(
      "/admin/settings/ai-status/retries/retry-now",
      { method: "POST" },
    ),
  retryAITaskNow: (ticketId: string) =>
    fetchAPI<import("./types").AIRetryQueueActionResponse>(
      `/admin/settings/ai-status/${encodeURIComponent(ticketId)}/retry-now`,
      { method: "POST" },
    ),
  rescheduleAITask: (ticketId: string, scheduledAt: string) =>
    fetchAPI<import("./types").AIRetryQueueActionResponse>(
      `/admin/settings/ai-status/${encodeURIComponent(ticketId)}/retry-schedule`,
      {
        method: "PUT",
        body: JSON.stringify({ scheduled_at: scheduledAt }),
      },
    ),
  getTicketIntelligenceStatus: () =>
    fetchAPI<import("./types").TicketIntelligenceStatus>("/ticket-intelligence/status"),
  getStatusDiagnostics: (area: import("./types").OperationalDiagnosticArea) =>
    fetchAPI<import("./types").OperationalDiagnosticsResponse>(
      `/admin/settings/status/diagnostics?area=${encodeURIComponent(area)}`
    ),
  getAITaskDiagnostics: (ticketId: string) =>
    fetchAPI<import("./types").OperationalDiagnosticsResponse>(
      `/admin/settings/ai-status/${encodeURIComponent(ticketId)}/diagnostics`
    ),
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
  getRoutingCatalogRecommendations: () =>
    fetchAPI<import("./types").RoutingCatalogRecommendationsResponse>(
      "/admin/routing-catalog/recommendations"
    ),
  // Intelligence agents
  getIntelOverview: (windowDays = 30) =>
    fetchAPI<import("./types").IntelligenceOverviewResponse>(
      `/intelligence/overview?window_days=${windowDays}`
    ),
  getIntelServiceQuality: (windowDays = 30) =>
    fetchAPI<import("./types").ServiceQualityResponse>(
      `/intelligence/service-quality?window_days=${windowDays}`
    ),
  getIntelSlaMonitoring: (windowDays = 30) =>
    fetchAPI<import("./types").SlaMonitoringResponse>(
      `/intelligence/sla-monitoring?window_days=${windowDays}`
    ),
  getIntelSlaAssigneeEvidence: (
    windowDays: number,
    assigneeSource: "provider" | "tickety" | "unmapped",
    assigneeId?: string | null,
  ) => {
    const params = new URLSearchParams({
      window_days: String(windowDays),
      assignee_source: assigneeSource,
    });
    if (assigneeId) params.set("assignee_id", assigneeId);
    return fetchAPI<import("./types").SlaAssigneeEvidenceResponse>(
      `/intelligence/sla-monitoring/assignee-evidence?${params.toString()}`
    );
  },
  getLevelZeroStudy: (months = 12) =>
    fetchAPI<import("./types").LevelZeroStudyResponse>(
      `/intelligence/level-zero-study?months=${months}`
    ),
  runLevelZeroStudy: (months = 12) =>
    fetchAPI<import("./types").LevelZeroStudy>(
      `/intelligence/level-zero-study?months=${months}`,
      { method: "POST" }
    ),
  getIntelAlerts: () =>
    fetchAPI<import("./types").IntelAlertsResponse>("/intelligence/alerts?window_days=30"),
  getIntelAlertsForWindow: (windowDays: number) =>
    fetchAPI<import("./types").IntelAlertsResponse>(
      `/intelligence/alerts?window_days=${windowDays}`
    ),
  getIntelPrioritize: () =>
    fetchAPI<import("./types").IntelPrioritizeResponse>("/intelligence/prioritize?window_days=30"),
  getIntelPrioritizeForWindow: (windowDays: number) =>
    fetchAPI<import("./types").IntelPrioritizeResponse>(
      `/intelligence/prioritize?window_days=${windowDays}`
    ),
  getIntelSla: () =>
    fetchAPI<import("./types").IntelSlaResponse>("/intelligence/sla?window_days=30"),
  getIntelSlaForWindow: (windowDays: number) =>
    fetchAPI<import("./types").IntelSlaResponse>(
      `/intelligence/sla?window_days=${windowDays}`
    ),
  getIntelTrends: () =>
    fetchAPI<import("./types").IntelTrendsResponse>("/intelligence/trends?window_days=30"),
  getIntelTrendsForWindow: (windowDays: number) =>
    fetchAPI<import("./types").IntelTrendsResponse>(
      `/intelligence/trends?window_days=${windowDays}`
    ),
  getIntelSystemic: (minCluster = 2) =>
    fetchAPI<import("./types").SystemicIssuesResponse>(
      `/intelligence/systemic?min_cluster=${minCluster}&window_days=30`
    ),
  getIntelSystemicForWindow: (minCluster: number, windowDays: number) =>
    fetchAPI<import("./types").SystemicIssuesResponse>(
      `/intelligence/systemic?min_cluster=${minCluster}&window_days=${windowDays}`
    ),
  getIntelWorkload: (windowDays = 30) =>
    fetchAPI<import("./types").IntelWorkloadResponse>(
      `/intelligence/workload?window_days=${windowDays}`
    ),
  getIntelHealth: (reporter: string) =>
    fetchAPI<import("./types").AccountHealth>(
      `/intelligence/health/${encodeURIComponent(reporter)}?window_days=30`
    ),
  getIntelHealthForWindow: (reporter: string, windowDays: number) =>
    fetchAPI<import("./types").AccountHealth>(
      `/intelligence/health/${encodeURIComponent(reporter)}?window_days=${windowDays}`
    ),
  getIntelRoute: (ticketId: string) =>
    fetchResolverRoute(`/intelligence/route/${ticketId}`),
  generateTicketRoute: (ticketId: string, force = false) =>
    fetchResolverRoute(`/tickets/${ticketId}/route?force=${force ? 1 : 0}`, {
      method: "POST",
    }),
  generateTicketSummary: (ticketId: string, force = false) =>
    fetchAPI<import("./types").TicketSummary>(
      `/tickets/${ticketId}/summary?force=${force ? 1 : 0}`,
      { method: "POST" }
    ),
  getRecommendedSolution: (ticketId: string, force = false) =>
    fetchAPI<import("./types").RecommendedSolution>(
      `/intelligence/resolve/${ticketId}?force=${force ? 1 : 0}`,
      { method: "POST" }
    ),
  getVersion: () => fetchAPI<import("./types").BuildInfo>("/version"),
  // Standalone ticketing
  updateTicket: (id: string, payload: Record<string, unknown>) =>
    fetchAPI<import("./types").Ticket>(`/tickets/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteTicket: (id: string) => fetchAPI<{ status: string }>(`/tickets/${id}`, { method: "DELETE" }),
  getComments: (ticketId: string, pagination?: { limit?: number; offset?: number }) => {
    const params = new URLSearchParams();
    if (pagination?.limit !== undefined) params.set("limit", String(pagination.limit));
    if (pagination?.offset !== undefined) params.set("offset", String(pagination.offset));
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return fetchAPI<import("./types").TicketComment[]>(`/tickets/${ticketId}/comments${query}`);
  },
  getAttachments: (ticketId: string) =>
    fetchAPI<import("./types").TicketAttachment[]>(`/tickets/${ticketId}/attachments`),
  addComment: (ticketId: string, body: string, isPrivate = false) =>
    fetchAPI<import("./types").TicketComment>(`/tickets/${ticketId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body, is_private: isPrivate }),
    }),
  getAuditLog: (ticketId: string) =>
    fetchAPI<import("./types").TicketAuditEntry[]>(`/tickets/${ticketId}/audit`),
  getCategories: () =>
    fetchAPI<import("./types").TicketCategory[]>("/categories"),
  createCategory: (name: string, description = "", color = "slate") =>
    fetchAPI<import("./types").TicketCategory>("/categories", {
      method: "POST",
      body: JSON.stringify({ name, description, color }),
    }),
  deleteCategory: (id: number) =>
    fetchAPI<{ status: string }>(`/categories/${id}`, { method: "DELETE" }),
  bulkAction: (ticketIds: string[], action: string, value?: string) =>
    fetchAPI<{ status: string; updated: number }>("/tickets/bulk", {
      method: "POST",
      body: JSON.stringify({ ticket_ids: ticketIds, action, value }),
    }),
  // Auth
  login: (email: string, password: string) =>
    fetchAPI<import("./types").AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => fetchAPI<{ status: string }>("/auth/logout", { method: "POST" }),
  getAuthMe: () => fetchAPI<import("./types").AuthContext>("/auth/me"),
  getSsoConfig: () => fetchAPI<import("./sso-login").SsoLoginConfig>("/auth/sso/config"),
  // Users / Agents CRUD
  getUsers: () => fetchAPI<import("./types").UserOut[]>("/users"),
  createUser: (payload: import("./types").UserCreateInput) =>
    fetchAPI<import("./types").UserOut>("/users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateUser: (id: string, payload: import("./types").UserUpdateInput) =>
    fetchAPI<import("./types").UserOut>(`/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteUser: (id: string) => fetchAPI<{ status: string }>(`/users/${id}`, { method: "DELETE" }),
  purgeUser: (id: string) => fetchAPI<{ status: string; user_id: string; removed_owned_records: number; cleared_history_references: number }>(`/users/${id}/purge`, { method: "DELETE" }),
  // Knowledge Base
  getKbArticles: async (options: {
    search?: string;
    category?: string;
    status?: "all" | "published" | "draft" | "archived";
    limit?: number;
    offset?: number;
  } = {}) => {
    const params = new URLSearchParams();
    if (options.search) params.set("search", options.search);
    if (options.category) params.set("category", options.category);
    if (options.status) params.set("status", options.status);
    params.set("limit", String(options.limit ?? 20));
    params.set("offset", String(options.offset ?? 0));
    const { data, response } = await fetchAPIResponse<import("./types").KbArticle[]>(
      `/kb?${params.toString()}`,
    );
    return {
      articles: data,
      hasMore: response.headers.get("x-has-more") === "true",
      limit: Number(response.headers.get("x-page-limit") ?? options.limit ?? 20),
      offset: Number(response.headers.get("x-page-offset") ?? options.offset ?? 0),
    };
  },
  getKbArticle: (id: string) => fetchAPI<import("./types").KbArticle>(`/kb/${id}`),
  createKbArticle: (payload: import("./types").KbArticleCreateInput) =>
    fetchAPI<import("./types").KbArticle>("/kb", { method: "POST", body: JSON.stringify(payload) }),
  updateKbArticle: (id: string, payload: Partial<import("./types").KbArticleCreateInput>) =>
    fetchAPI<import("./types").KbArticle>(`/kb/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteKbArticle: (id: string) => fetchAPI<{ status: string }>(`/kb/${id}`, { method: "DELETE" }),
  getKbCategories: (includeUnpublished = false) => fetchAPI<{ categories: string[] }>(
    `/kb/categories${includeUnpublished ? "?status=all" : ""}`,
  ),
  kbFeedback: (id: string, helpful: boolean) =>
    fetchAPI<{ status: string }>(`/kb/${id}/feedback`, { method: "POST", body: JSON.stringify({ helpful }) }),
  linkKbToTicket: (ticketId: string, articleId: string) =>
    fetchAPI<{ status: string }>(`/tickets/${ticketId}/kb/${articleId}`, { method: "POST" }),
  getTicketKbLinks: (ticketId: string) => fetchAPI<import("./types").KbArticle[]>(`/tickets/${ticketId}/kb`),
  // Config
  getStatusConfig: () => fetchAPI<import("./types").TicketStatusConfig[]>("/config/statuses"),
  createStatusConfig: (payload: Partial<import("./types").TicketStatusConfig>) =>
    fetchAPI<import("./types").TicketStatusConfig>("/config/statuses", { method: "POST", body: JSON.stringify(payload) }),
  deleteStatusConfig: (id: number) => fetchAPI<{ status: string }>(`/config/statuses/${id}`, { method: "DELETE" }),
  getPriorityConfig: () => fetchAPI<import("./types").TicketPriorityConfig[]>("/config/priorities"),
  createPriorityConfig: (payload: Partial<import("./types").TicketPriorityConfig>) =>
    fetchAPI<import("./types").TicketPriorityConfig>("/config/priorities", { method: "POST", body: JSON.stringify(payload) }),
  deletePriorityConfig: (id: number) => fetchAPI<{ status: string }>(`/config/priorities/${id}`, { method: "DELETE" }),
  getNotificationConfig: () => fetchAPI<import("./types").NotificationConfig[]>("/config/notifications"),
  updateNotificationConfig: (event: string, enabled: boolean, channels: string) =>
    fetchAPI<import("./types").NotificationConfig>(`/config/notifications/${event}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled, channels }),
    }),
  // Reports
  getReportSummary: (filters: import("./types").ReportFilters) =>
    fetchAPI<import("./types").ReportSummary>(reportPath("/reports/summary", filters)),
  getReportVolume: (filters: import("./types").ReportFilters) =>
    fetchAPI<{ days: string[]; counts: number[] }>(reportPath("/reports/volume", filters)),
  getReportByCategory: (filters: import("./types").ReportFilters) =>
    fetchAPI<import("./types").ReportByCategoryResponse>(reportPath("/reports/by-category", filters)),
  getReportByStatus: (filters: import("./types").ReportFilters) =>
    fetchAPI<{ statuses: string[]; counts: number[] }>(reportPath("/reports/by-status", filters)),
  getReportSlaCompliance: (filters: import("./types").ReportFilters) =>
    fetchAPI<Record<string, { total: number; breached: number; compliance: number }>>(
      reportPath("/reports/sla-compliance", filters)
    ),
  getReportResolutionTime: (filters: import("./types").ReportFilters) =>
    fetchAPI<import("./types").ReportResolutionTimeResponse>(reportPath("/reports/resolution-time", filters)),
  getReportOptions: () =>
    fetchAPI<import("./types").ReportOptions>("/reports/options"),
  getReportSeries: (
    filters: import("./types").ReportFilters,
    metric: import("./types").ReportMetric,
    groupBy: import("./types").ReportGroupBy,
  ) => {
    const path = reportPath("/reports/series", filters);
    return fetchAPI<import("./types").ReportSeriesResponse>(
      `${path}&metric=${encodeURIComponent(metric)}&group_by=${encodeURIComponent(groupBy)}`,
    );
  },
  downloadReportCsv,
  // Projects
  getProjects: () => fetchAPI<import("./types").Project[]>("/projects"),
  createProject: (payload: { name: string; key: string; description?: string; lead_id?: string }) =>
    fetchAPI<import("./types").Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: { name?: string; description?: string; lead_id?: string; status?: string }) =>
    fetchAPI<import("./types").Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (id: string) => fetchAPI<{ status: string }>(`/projects/${id}`, { method: "DELETE" }),
  // Service Catalog
  getServicesPage: async (options: {
    category?: string;
    search?: string;
    isActive?: boolean;
    limit?: number;
    offset?: number;
  } = {}) => {
    const limit = options.limit ?? 50;
    const offset = options.offset ?? 0;
    const params = new URLSearchParams();
    if (options.category) params.set("category", options.category);
    if (options.search?.trim()) params.set("search", options.search.trim());
    if (options.isActive !== undefined) params.set("is_active", String(options.isActive));
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    const { data, response } = await fetchAPIResponse<import("./types").ServiceItem[]>(
      `/services?${params.toString()}`,
    );
    const readCount = (name: string, fallback = 0) => {
      const raw = response.headers.get(name);
      const value = raw === null ? Number.NaN : Number(raw);
      return Number.isInteger(value) && value >= 0 ? value : fallback;
    };
    let categoryOptions: string[] = [];
    try {
      const decoded = JSON.parse(response.headers.get("x-service-category-options") || "[]");
      if (Array.isArray(decoded)) {
        categoryOptions = decoded.filter(
          (value): value is string => typeof value === "string" && value.length <= 255 && !value.includes("\0"),
        );
      }
    } catch {
      categoryOptions = [];
    }
    const pageLimit = readCount("x-page-limit", limit) || limit;
    const pageOffset = readCount("x-page-offset", offset);
    const hasMoreHeader = response.headers.get("x-has-more");
    return {
      services: data,
      limit: pageLimit,
      offset: pageOffset,
      hasMore: hasMoreHeader === "true"
        || (hasMoreHeader !== "false" && data.length >= pageLimit),
      summary: {
        total: readCount("x-service-total"),
        active: readCount("x-service-active"),
        categoryCount: readCount("x-service-category-count"),
        categoryOptions,
        categoryOptionsTruncated: response.headers.get("x-service-category-options-truncated") === "true",
      },
    } satisfies import("./types").ServicePage;
  },
  createService: (payload: { name: string; description?: string; category?: string | null; pricing?: string | null; sla_hours?: number | null; approval_required?: boolean }) =>
    fetchAPI<import("./types").ServiceItem>("/services", { method: "POST", body: JSON.stringify(payload) }),
  updateService: (id: string, payload: Partial<import("./types").ServiceItem>) =>
    fetchAPI<import("./types").ServiceItem>(`/services/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteService: (id: string) => fetchAPI<{ status: string }>(`/services/${id}`, { method: "DELETE" }),
  getServiceRequestsPage: async (options: {
    search?: string;
    serviceItemId?: string;
    approvalStatus?: string;
    fulfillmentStatus?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const limit = options.limit ?? 50;
    const offset = options.offset ?? 0;
    const params = new URLSearchParams();
    if (options.search?.trim()) params.set("search", options.search.trim());
    if (options.serviceItemId) params.set("service_item_id", options.serviceItemId);
    if (options.approvalStatus) params.set("approval_status", options.approvalStatus);
    if (options.fulfillmentStatus) params.set("fulfillment_status", options.fulfillmentStatus);
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    const { data, response } = await fetchAPIResponse<import("./types").ServiceRequest[]>(
      `/service-requests?${params.toString()}`,
    );
    const readCount = (name: string, fallback = 0) => {
      const raw = response.headers.get(name);
      const value = raw === null ? Number.NaN : Number(raw);
      return Number.isInteger(value) && value >= 0 ? value : fallback;
    };
    const pageLimit = readCount("x-page-limit", limit) || limit;
    const pageOffset = readCount("x-page-offset", offset);
    const hasMoreHeader = response.headers.get("x-has-more");
    return {
      requests: data,
      limit: pageLimit,
      offset: pageOffset,
      hasMore: hasMoreHeader === "true"
        || (hasMoreHeader !== "false" && data.length >= pageLimit),
      summary: {
        total: readCount("x-service-request-total"),
        open: readCount("x-service-request-open"),
        pending: readCount("x-service-request-pending"),
        pendingApproval: readCount("x-service-request-pending-approval"),
        awaitingFulfillment: readCount("x-service-request-awaiting-fulfillment"),
      },
    } satisfies import("./types").ServiceRequestPage;
  },
  createServiceRequest: (ticketId: string, serviceItemId: string, quantity: number, justification: string) =>
    fetchAPI<import("./types").ServiceRequest>("/service-requests", {
      method: "POST", body: JSON.stringify({ ticket_id: ticketId, service_item_id: serviceItemId, quantity, justification }),
    }),
  decideServiceRequestApproval: (requestId: string, decision: "approved" | "rejected", comment = "") =>
    fetchAPI<import("./types").ServiceRequest>(`/service-requests/${requestId}/approval`, {
      method: "PATCH",
      body: JSON.stringify({ decision, comment }),
    }),
  updateServiceRequestFulfillment: (requestId: string, status: "fulfilled" | "cancelled", deliveryNotes = "") =>
    fetchAPI<import("./types").ServiceRequest>(`/service-requests/${requestId}/fulfillment`, {
      method: "PATCH",
      body: JSON.stringify({ status, delivery_notes: deliveryNotes }),
    }),
  // Problem Management
  getProblemsPage: async (options: {
    status?: string;
    search?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const limit = options.limit ?? 25;
    const offset = options.offset ?? 0;
    const params = new URLSearchParams();
    if (options.status) params.set("status", options.status);
    if (options.search?.trim()) params.set("search", options.search.trim());
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    const { data, response } = await fetchAPIResponse<import("./types").Problem[]>(
      `/problems?${params.toString()}`,
    );
    const readNonNegativeHeader = (...names: string[]) => {
      for (const name of names) {
        const raw = response.headers.get(name);
        if (raw === null) continue;
        const value = Number(raw);
        if (Number.isInteger(value) && value >= 0) return value;
      }
      return undefined;
    };
    const pageLimit = readNonNegativeHeader("x-page-limit") || limit;
    const pageOffset = readNonNegativeHeader("x-page-offset") ?? offset;
    const hasMoreHeader = response.headers.get("x-page-has-more")
      ?? response.headers.get("x-has-more");
    return {
      problems: data,
      limit: pageLimit,
      offset: pageOffset,
      total: readNonNegativeHeader("x-page-total"),
      hasMore: hasMoreHeader === "true"
        || (hasMoreHeader !== "false" && data.length >= pageLimit),
      summary: {
        total: readNonNegativeHeader("x-problems-total", "x-problem-total") ?? 0,
        investigating: readNonNegativeHeader(
          "x-problems-investigating",
          "x-problem-investigating",
        ) ?? 0,
        knownErrors: readNonNegativeHeader(
          "x-problems-known-errors",
          "x-problem-known-errors",
        ) ?? 0,
        linkedTickets: readNonNegativeHeader(
          "x-problems-linked-tickets",
          "x-problem-linked-tickets",
        ) ?? 0,
      },
    };
  },
  getProblem: (id: string) => fetchAPI<import("./types").Problem>(`/problems/${id}`),
  createProblem: (payload: { title: string; description?: string; priority?: string; category?: string | null; assigned_to?: string | null; impact_scope?: string | null }) =>
    fetchAPI<import("./types").Problem>("/problems", { method: "POST", body: JSON.stringify(payload) }),
  updateProblem: (id: string, payload: Partial<import("./types").Problem>) =>
    fetchAPI<import("./types").Problem>(`/problems/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProblem: (id: string) => fetchAPI<{ status: string }>(`/problems/${id}`, { method: "DELETE" }),
  linkTicketToProblem: (problemId: string, ticketId: string) =>
    fetchAPI<{ status: string }>(`/problems/${problemId}/link/${ticketId}`, { method: "POST" }),
  unlinkTicketFromProblem: (problemId: string, ticketId: string) =>
    fetchAPI<{ status: string }>(`/problems/${problemId}/link/${ticketId}`, { method: "DELETE" }),
  getProblemTicketsPage: async (
    problemId: string,
    { limit = 50, offset = 0 }: { limit?: number; offset?: number } = {},
  ) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    const { data, response } = await fetchAPIResponse<import("./types").Ticket[]>(
      `/problems/${encodeURIComponent(problemId)}/tickets?${params.toString()}`,
    );
    const limitHeader = response.headers.get("x-page-limit");
    const offsetHeader = response.headers.get("x-page-offset");
    const hasMoreHeader = response.headers.get("x-has-more")
      ?? response.headers.get("x-page-has-more");
    const responseLimit = limitHeader === null ? Number.NaN : Number(limitHeader);
    const responseOffset = offsetHeader === null ? Number.NaN : Number(offsetHeader);
    const pageLimit = Number.isInteger(responseLimit) && responseLimit > 0 ? responseLimit : limit;
    return {
      tickets: data,
      limit: pageLimit,
      offset: Number.isInteger(responseOffset) && responseOffset >= 0 ? responseOffset : offset,
      hasMore: hasMoreHeader === "true",
    };
  },
  // Change Management
  getChangesPage: async (options: { status?: string; search?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams();
    if (options.status) params.set("status", options.status);
    if (options.search) params.set("search", options.search);
    params.set("limit", String(options.limit ?? 25));
    params.set("offset", String(options.offset ?? 0));
    const { data, response } = await fetchAPIResponse<import("./types").ChangeRecord[]>(`/changes?${params.toString()}`);
    return {
      changes: data,
      limit: Number(response.headers.get("x-page-limit")) || options.limit || 25,
      offset: Number(response.headers.get("x-page-offset")) || options.offset || 0,
      hasMore: response.headers.get("x-has-more") === "true",
      summary: {
        awaitingReview: Number(response.headers.get("x-change-awaiting-review")) || 0,
        inProgress: Number(response.headers.get("x-change-in-progress")) || 0,
        highRisk: Number(response.headers.get("x-change-high-risk")) || 0,
      },
    } satisfies import("./types").ChangePage;
  },
  getChange: (id: string) => fetchAPI<import("./types").ChangeRecord>(`/changes/${id}`),
  createChange: (payload: Partial<import("./types").ChangeRecord>) =>
    fetchAPI<import("./types").ChangeRecord>("/changes", { method: "POST", body: JSON.stringify(payload) }),
  updateChange: (id: string, payload: Partial<import("./types").ChangeRecord>) =>
    fetchAPI<import("./types").ChangeRecord>(`/changes/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteChange: (id: string) => fetchAPI<{ status: string }>(`/changes/${id}`, { method: "DELETE" }),
  getChangeApprovals: async (
    changeId: string,
    { limit = 50, offset = 0 }: { limit?: number; offset?: number } = {},
  ) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    const { data, response } = await fetchAPIResponse<import("./types").ChangeApproval[]>(
      `/changes/${encodeURIComponent(changeId)}/approvals?${params.toString()}`,
    );
    const limitHeader = response.headers.get("x-page-limit");
    const offsetHeader = response.headers.get("x-page-offset");
    const hasMoreHeader = response.headers.get("x-has-more");
    const responseLimit = limitHeader === null ? Number.NaN : Number(limitHeader);
    const responseOffset = offsetHeader === null ? Number.NaN : Number(offsetHeader);
    const pageLimit = Number.isInteger(responseLimit) && responseLimit > 0 ? responseLimit : limit;
    return {
      approvals: data,
      limit: pageLimit,
      offset: Number.isInteger(responseOffset) && responseOffset >= 0 ? responseOffset : offset,
      hasMore: hasMoreHeader === "true" || (hasMoreHeader !== "false" && data.length >= pageLimit),
    } satisfies import("./types").ChangeApprovalPage;
  },
  addChangeApproval: (changeId: string, approverId: string) =>
    fetchAPI<import("./types").ChangeApproval>(`/changes/${changeId}/approvals`, { method: "POST", body: JSON.stringify({ approver_id: approverId }) }),
  decideApproval: (changeId: string, approverId: string, decision: string, comment?: string) =>
    fetchAPI<{ status: string }>(`/changes/${changeId}/approvals/${approverId}`, {
      method: "PATCH",
      body: JSON.stringify({ decision, comment: comment || "" }),
    }),
  // Assets
  getAssetsPage: async (options: {
    assetType?: string;
    status?: string;
    search?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const limit = options.limit ?? 50;
    const offset = options.offset ?? 0;
    const params = new URLSearchParams();
    if (options.assetType) params.set("asset_type", options.assetType);
    if (options.status) params.set("status", options.status);
    if (options.search?.trim()) params.set("search", options.search.trim());
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    const { data, response } = await fetchAPIResponse<import("./types").Asset[]>(
      `/assets?${params.toString()}`,
    );
    const limitHeader = response.headers.get("x-page-limit");
    const offsetHeader = response.headers.get("x-page-offset");
    const hasMoreHeader = response.headers.get("x-has-more");
    const responseLimit = limitHeader === null ? Number.NaN : Number(limitHeader);
    const responseOffset = offsetHeader === null ? Number.NaN : Number(offsetHeader);
    const pageLimit = Number.isInteger(responseLimit) && responseLimit > 0 ? responseLimit : limit;
    return {
      assets: data,
      limit: pageLimit,
      offset: Number.isInteger(responseOffset) && responseOffset >= 0 ? responseOffset : offset,
      hasMore: hasMoreHeader === "true" || (hasMoreHeader !== "false" && data.length >= pageLimit),
    } satisfies import("./types").AssetPage;
  },
  getAsset: (id: string) => fetchAPI<import("./types").Asset>(`/assets/${id}`),
  createAsset: (payload: Partial<import("./types").Asset>) =>
    fetchAPI<import("./types").Asset>("/assets", { method: "POST", body: JSON.stringify(payload) }),
  updateAsset: (id: string, payload: Partial<import("./types").Asset>) =>
    fetchAPI<import("./types").Asset>(`/assets/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAsset: (id: string) => fetchAPI<{ status: string }>(`/assets/${id}`, { method: "DELETE" }),
  getAssetStats: () => fetchAPI<{ total: number; by_type: Record<string, number> }>("/assets/stats"),
  // Surveys / CSAT
  getSurveyTemplates: () => fetchAPI<import("./types").SurveyTemplate[]>("/surveys/templates"),
  getSurveysPage: async ({ limit = 50, offset = 0 }: { limit?: number; offset?: number } = {}) => {
    const { data, response } = await fetchAPIResponse<import("./types").SurveyOut[]>(
      `/surveys?limit=${limit}&offset=${offset}`,
    );
    return {
      surveys: data,
      limit: Number(response.headers.get("x-page-limit")) || limit,
      offset: Number(response.headers.get("x-page-offset")) || offset,
      hasMore: response.headers.get("x-has-more") === "true",
    };
  },
  getSurveyEligibleTickets: async ({ search, limit = 50, offset = 0 }: { search?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search?.trim()) params.set("search", search.trim());
    const { data, response } = await fetchAPIResponse<import("./types").Ticket[]>(
      `/surveys/eligible-tickets?${params.toString()}`,
    );
    return {
      tickets: data,
      limit: Number(response.headers.get("x-page-limit")) || limit,
      offset: Number(response.headers.get("x-page-offset")) || offset,
      hasMore: response.headers.get("x-has-more") === "true",
    } satisfies import("./types").TicketPage;
  },
  sendSurvey: (ticketId: string, templateId: number) =>
    fetchAPI<import("./types").SurveyOut>("/surveys/send", { method: "POST", body: JSON.stringify({ ticket_id: ticketId, template_id: templateId }) }),
  lookupPortalSurvey: (token: string) =>
    fetchAPI<import("./types").PortalSurveyQuestion>("/portal/survey/lookup", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  respondPortalSurvey: (token: string, rating: number, comment: string) =>
    fetchAPI<import("./types").PortalSurveySubmitted>("/portal/survey/respond", {
      method: "POST",
      body: JSON.stringify({ token, rating, comment }),
    }),
  getSurveyStats: () => fetchAPI<{ total_sent: number; responded: number; response_rate: number; avg_rating: number; distribution: Record<string, number> }>("/surveys/stats"),
  // Time Tracking
  getTimeEntries: async (options: {
    ticketId?: string;
    userId?: string;
    teamId?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const limit = options.limit ?? 25;
    const offset = options.offset ?? 0;
    const params = new URLSearchParams();
    if (options.ticketId) params.set("ticket_id", options.ticketId);
    if (options.userId) params.set("user_id", options.userId);
    if (options.teamId) params.set("team_id", options.teamId);
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    const { data, response } = await fetchAPIResponse<import("./types").TimeEntry[]>(
      `/time-entries?${params.toString()}`,
    );
    return {
      entries: data,
      limit: Number(response.headers.get("x-page-limit")) || limit,
      offset: Number(response.headers.get("x-page-offset")) || offset,
      hasMore: response.headers.get("x-has-more") === "true",
    } satisfies import("./types").TimeEntryPage;
  },
  createTimeEntry: (ticketId: string, description: string, minutes: number) =>
    fetchAPI<import("./types").TimeEntry>("/time-entries", { method: "POST", body: JSON.stringify({ ticket_id: ticketId, description, minutes }) }),
  getTicketTimeEntries: async (ticketId: string, options: { userId?: string; limit?: number; offset?: number } = {}) => {
    const limit = options.limit ?? 25;
    const offset = options.offset ?? 0;
    const params = new URLSearchParams();
    if (options.userId) params.set("user_id", options.userId);
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    const { data, response } = await fetchAPIResponse<import("./types").TimeEntry[]>(
      `/time-entries/ticket/${encodeURIComponent(ticketId)}?${params.toString()}`,
    );
    return {
      entries: data,
      limit: Number(response.headers.get("x-page-limit")) || limit,
      offset: Number(response.headers.get("x-page-offset")) || offset,
      hasMore: response.headers.get("x-has-more") === "true",
    } satisfies import("./types").TimeEntryPage;
  },
  getTimeSummary: (timeZone: string, options: { ticketId?: string; userId?: string; teamId?: string } = {}) => {
    const params = new URLSearchParams({ time_zone: timeZone });
    if (options.ticketId) params.set("ticket_id", options.ticketId);
    if (options.userId) params.set("user_id", options.userId);
    if (options.teamId) params.set("team_id", options.teamId);
    return fetchAPI<{ total_hours: number; today_hours: number; ticket_count: number; average_hours_per_ticket: number }>(`/time-entries/summary?${params.toString()}`);
  },
  // Self-Service Portal
  portalCreateTicket: (subject: string, description: string, reporter: string, priority = "P3") =>
    fetchAPI<import("./types").PortalTicketCreated>("/portal/tickets", {
      method: "POST",
      body: JSON.stringify({ subject, description, reporter, priority }),
    }),
  portalGetTicket: (accessToken: string) => {
    return fetchAPI<import("./types").PortalTicket>("/portal/tickets", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  },
};
