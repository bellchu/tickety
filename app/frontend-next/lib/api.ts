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

export const api = {
  getHealth: () => fetchAPI<{ status: string; mode: "demo" | "production" }>("/health"),
  getTickets: () => fetchAPI<import("./types").Ticket[]>("/tickets"),
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
  fetchTickets: (days: number, overwrite = false) =>
    fetchAPI<{ status: string; result: import("./types").FetchTicketsResult }>(
      `/admin/sync/fetch?days=${days}&overwrite=${overwrite ? 1 : 0}`,
      { method: "POST" }
    ),
  syncExternalUsers: () =>
    fetchAPI<{ status: string; result: import("./types").ExternalUserSyncResult }>(
      "/admin/sync/external-users", { method: "POST" }
    ),
  getExternalUsers: () =>
    fetchAPI<import("./types").ExternalUserListResponse>("/admin/external-users"),
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
  // Knowledge Base
  getKbArticles: async (search?: string, category?: string) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (category) params.set("category", category);
    params.set("limit", "500");
    params.set("offset", "0");
    const { data, response } = await fetchAPIResponse<import("./types").KbArticle[]>(
      `/kb?${params.toString()}`,
    );
    return {
      articles: data,
      hasMore: response.headers.get("x-has-more") === "true",
    };
  },
  getKbArticle: (id: string) => fetchAPI<import("./types").KbArticle>(`/kb/${id}`),
  createKbArticle: (payload: import("./types").KbArticleCreateInput) =>
    fetchAPI<import("./types").KbArticle>("/kb", { method: "POST", body: JSON.stringify(payload) }),
  updateKbArticle: (id: string, payload: Partial<import("./types").KbArticleCreateInput>) =>
    fetchAPI<import("./types").KbArticle>(`/kb/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteKbArticle: (id: string) => fetchAPI<{ status: string }>(`/kb/${id}`, { method: "DELETE" }),
  getKbCategories: () => fetchAPI<{ categories: string[] }>("/kb/categories"),
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
  getReportSummary: () => fetchAPI<import("./types").ReportSummary>("/reports/summary"),
  getReportVolume: () => fetchAPI<{ days: string[]; counts: number[] }>("/reports/volume"),
  getReportByCategory: () =>
    fetchAPI<import("./types").ReportByCategoryResponse>("/reports/by-category"),
  getReportByStatus: () => fetchAPI<{ statuses: string[]; counts: number[] }>("/reports/by-status"),
  getReportSlaCompliance: () =>
    fetchAPI<Record<string, { total: number; breached: number; compliance: number }>>("/reports/sla-compliance"),
  getReportResolutionTime: () =>
    fetchAPI<import("./types").ReportResolutionTimeResponse>("/reports/resolution-time"),
  // Projects
  getProjects: () => fetchAPI<import("./types").Project[]>("/projects"),
  createProject: (payload: { name: string; key: string; description?: string; lead_id?: string }) =>
    fetchAPI<import("./types").Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: { name?: string; description?: string; lead_id?: string; status?: string }) =>
    fetchAPI<import("./types").Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (id: string) => fetchAPI<{ status: string }>(`/projects/${id}`, { method: "DELETE" }),
  // Service Catalog
  getServices: (category?: string) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    return fetchAPI<import("./types").ServiceItem[]>(`/services${params.toString() ? "?" + params.toString() : ""}`);
  },
  createService: (payload: { name: string; description?: string; category?: string; pricing?: string; sla_hours?: number; approval_required?: boolean }) =>
    fetchAPI<import("./types").ServiceItem>("/services", { method: "POST", body: JSON.stringify(payload) }),
  updateService: (id: string, payload: Partial<import("./types").ServiceItem>) =>
    fetchAPI<import("./types").ServiceItem>(`/services/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteService: (id: string) => fetchAPI<{ status: string }>(`/services/${id}`, { method: "DELETE" }),
  getServiceRequests: () => fetchAPI<import("./types").ServiceRequest[]>("/service-requests"),
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
  getProblems: (status?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    return fetchAPI<import("./types").Problem[]>(`/problems${params.toString() ? "?" + params.toString() : ""}`);
  },
  getProblem: (id: string) => fetchAPI<import("./types").Problem>(`/problems/${id}`),
  createProblem: (payload: { title: string; description?: string; priority?: string; category?: string; assigned_to?: string; impact_scope?: string }) =>
    fetchAPI<import("./types").Problem>("/problems", { method: "POST", body: JSON.stringify(payload) }),
  updateProblem: (id: string, payload: Partial<import("./types").Problem>) =>
    fetchAPI<import("./types").Problem>(`/problems/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProblem: (id: string) => fetchAPI<{ status: string }>(`/problems/${id}`, { method: "DELETE" }),
  linkTicketToProblem: (problemId: string, ticketId: string) =>
    fetchAPI<{ status: string }>(`/problems/${problemId}/link/${ticketId}`, { method: "POST" }),
  unlinkTicketFromProblem: (problemId: string, ticketId: string) =>
    fetchAPI<{ status: string }>(`/problems/${problemId}/link/${ticketId}`, { method: "DELETE" }),
  getProblemTickets: (problemId: string) => fetchAPI<import("./types").Ticket[]>(`/problems/${problemId}/tickets`),
  // Change Management
  getChanges: (status?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    return fetchAPI<import("./types").ChangeRecord[]>(`/changes${params.toString() ? "?" + params.toString() : ""}`);
  },
  getChange: (id: string) => fetchAPI<import("./types").ChangeRecord>(`/changes/${id}`),
  createChange: (payload: Partial<import("./types").ChangeRecord>) =>
    fetchAPI<import("./types").ChangeRecord>("/changes", { method: "POST", body: JSON.stringify(payload) }),
  updateChange: (id: string, payload: Partial<import("./types").ChangeRecord>) =>
    fetchAPI<import("./types").ChangeRecord>(`/changes/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteChange: (id: string) => fetchAPI<{ status: string }>(`/changes/${id}`, { method: "DELETE" }),
  getChangeApprovals: (changeId: string) => fetchAPI<import("./types").ChangeApproval[]>(`/changes/${changeId}/approvals`),
  addChangeApproval: (changeId: string, approverId: string) =>
    fetchAPI<import("./types").ChangeApproval>(`/changes/${changeId}/approvals`, { method: "POST", body: JSON.stringify({ approver_id: approverId }) }),
  decideApproval: (changeId: string, approverId: string, decision: string, comment?: string) =>
    fetchAPI<{ status: string }>(`/changes/${changeId}/approvals/${approverId}`, {
      method: "PATCH",
      body: JSON.stringify({ decision, comment: comment || "" }),
    }),
  // Assets
  getAssets: (assetType?: string, status?: string, search?: string) => {
    const params = new URLSearchParams();
    if (assetType) params.set("asset_type", assetType);
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    return fetchAPI<import("./types").Asset[]>(`/assets${params.toString() ? "?" + params.toString() : ""}`);
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
  getSurveys: () => fetchAPI<import("./types").SurveyOut[]>("/surveys"),
  sendSurvey: (ticketId: string, templateId: number) =>
    fetchAPI<import("./types").SurveyOut>("/surveys/send", { method: "POST", body: JSON.stringify({ ticket_id: ticketId, template_id: templateId }) }),
  respondSurvey: (surveyId: string, rating: number, comment: string) =>
    fetchAPI<{ status: string }>(`/surveys/${surveyId}/respond`, { method: "POST", body: JSON.stringify({ rating, comment }) }),
  getSurveyStats: () => fetchAPI<{ total_sent: number; responded: number; response_rate: number; avg_rating: number; distribution: Record<string, number> }>("/surveys/stats"),
  // Time Tracking
  getTimeEntries: (ticketId?: string) => {
    const params = new URLSearchParams();
    if (ticketId) params.set("ticket_id", ticketId);
    return fetchAPI<import("./types").TimeEntry[]>(`/time-entries${params.toString() ? "?" + params.toString() : ""}`);
  },
  createTimeEntry: (ticketId: string, description: string, minutes: number) =>
    fetchAPI<import("./types").TimeEntry>("/time-entries", { method: "POST", body: JSON.stringify({ ticket_id: ticketId, description, minutes }) }),
  getTicketTimeEntries: (ticketId: string) => fetchAPI<import("./types").TimeEntry[]>(`/time-entries/ticket/${ticketId}`),
  getTimeSummary: () => fetchAPI<{ total_hours: number; today_hours: number }>("/time-entries/summary"),
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
