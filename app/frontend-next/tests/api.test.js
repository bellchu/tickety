const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadApi() {
  const filename = path.join(__dirname, "..", "lib", "api.ts");
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  const compile = new Function("require", "exports", "module", output);
  compile((specifier) => {
    if (specifier === "@tanstack/react-query") return { QueryClient: class QueryClient {} };
    throw new Error(`Unexpected module: ${specifier}`);
  }, loaded.exports, loaded);
  return loaded.exports;
}

test("deleteCategory keeps HTTP failures on the API error path", async () => {
  const { api, APIError } = loadApi();
  const originalFetch = global.fetch;
  global.fetch = async (url, options) => {
    assert.equal(url, "/api/categories/42");
    assert.equal(options.method, "DELETE");
    return new Response(JSON.stringify({ detail: "Category is still in use" }), { status: 409 });
  };

  try {
    await assert.rejects(
      api.deleteCategory(42),
      (error) => error instanceof APIError && error.status === 409 && error.message === "Category is still in use",
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test("getComments supports bounded history pagination without changing the default route", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(url);
    return new Response("[]", { status: 200 });
  };

  try {
    await api.getComments("ticket-1");
    await api.getComments("ticket-1", { limit: 500, offset: 1000 });
    assert.deepEqual(calls, [
      "/api/tickets/ticket-1/comments",
      "/api/tickets/ticket-1/comments?limit=500&offset=1000",
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

test("assignee SLA evidence keeps the identity source and encodes provider IDs", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(String(url));
    return new Response("{}", { status: 200 });
  };

  try {
    await api.getIntelSlaAssigneeEvidence(90, "provider", "agent / one & two");
    await api.getIntelSlaAssigneeEvidence(30, "unmapped", null);
    assert.deepEqual(calls, [
      "/api/intelligence/sla-monitoring/assignee-evidence?window_days=90&assignee_source=provider&assignee_id=agent+%2F+one+%26+two",
      "/api/intelligence/sla-monitoring/assignee-evidence?window_days=30&assignee_source=unmapped",
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

test("every report request and CSV export use the same encoded criteria", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(String(url));
    const headers = String(url).includes("/reports/export")
      ? {
          "content-disposition": 'attachment; filename="filtered-report.csv"',
          "content-type": "text/csv",
          "x-report-rows": "3",
        }
      : { "content-type": "application/json" };
    return new Response(
      String(url).includes("/reports/export") ? "Ticket ID\nT-1\n" : "{}",
      { status: 200, headers },
    );
  };
  const filters = {
    startAt: "2026-08-01T08:15:00.000Z",
    endAt: "2026-08-25T17:45:00.000Z",
    dateField: "resolved",
    status: "Closed & verified",
    priority: "P1",
    category: "Network / VPN",
    assigneeId: "agent & one",
    source: "Fresh Service",
    ticketType: "service_request",
    resolutionState: "resolved",
    slaState: "within_sla",
  };

  try {
    await Promise.all([
      api.getReportSummary(filters),
      api.getReportVolume(filters),
      api.getReportByCategory(filters),
      api.getReportByStatus(filters),
      api.getReportSlaCompliance(filters),
      api.getReportResolutionTime(filters),
      api.getReportSeries(filters, "avg_resolution_hours", "assignee"),
    ]);
    const exported = await api.downloadReportCsv(filters);

    assert.equal(calls.length, 8);
    for (const call of calls) {
      const url = new URL(call, "https://tickety.nexora.com");
      assert.equal(url.searchParams.get("start_at"), filters.startAt);
      assert.equal(url.searchParams.get("end_at"), filters.endAt);
      assert.equal(url.searchParams.get("date_field"), "resolved");
      assert.equal(url.searchParams.get("status"), "Closed & verified");
      assert.equal(url.searchParams.get("priority"), "P1");
      assert.equal(url.searchParams.get("category"), "Network / VPN");
      assert.equal(url.searchParams.get("assignee_id"), "agent & one");
      assert.equal(url.searchParams.get("source"), "Fresh Service");
      assert.equal(url.searchParams.get("ticket_type"), "service_request");
      assert.equal(url.searchParams.get("resolution_state"), "resolved");
      assert.equal(url.searchParams.get("sla_state"), "within_sla");
    }
    const seriesCall = new URL(calls.find((call) => call.includes("/reports/series")), "https://tickety.nexora.com");
    assert.equal(seriesCall.searchParams.get("metric"), "avg_resolution_hours");
    assert.equal(seriesCall.searchParams.get("group_by"), "assignee");
    assert.equal(exported.filename, "filtered-report.csv");
    assert.equal(exported.rowCount, 3);
    assert.equal(await exported.blob.text(), "Ticket ID\nT-1\n");
  } finally {
    global.fetch = originalFetch;
  }
});

test("external directory requests encode server-side search, filters, and pagination", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(url);
    return new Response(JSON.stringify({ users: [], total: 0, limit: 25, offset: 50, has_more: false }), { status: 200 });
  };

  try {
    await api.getExternalUsers();
    await api.getExternalUsers({ search: "Alex & team", userType: "requester", limit: 25, offset: 50 });
    assert.deepEqual(calls, [
      "/api/admin/external-users",
      "/api/admin/external-users?search=Alex+%26+team&user_type=requester&limit=25&offset=50",
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

test("time summary sends the browser's IANA time zone", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    assert.equal(url, "/api/time-entries/summary?time_zone=America%2FToronto");
    return new Response(JSON.stringify({ total_hours: 8, today_hours: 2 }), { status: 200 });
  };

  try {
    assert.deepEqual(await api.getTimeSummary("America/Toronto"), {
      total_hours: 8,
      today_hours: 2,
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test("time entry list and summary share the same explicit self scope", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(url);
    return new Response(JSON.stringify(url.includes("summary")
      ? { total_hours: 3, today_hours: 1, ticket_count: 2, average_hours_per_ticket: 1.5 }
      : []), { status: 200 });
  };

  try {
    await api.getTimeEntries({ ticketId: "ticket-1", userId: "user-1" });
    await api.getTimeSummary("UTC", { ticketId: "ticket-1", userId: "user-1" });
    assert.deepEqual(calls, [
      "/api/time-entries?ticket_id=ticket-1&user_id=user-1&limit=25&offset=0",
      "/api/time-entries/summary?time_zone=UTC&ticket_id=ticket-1&user_id=user-1",
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

test("time entry list clients preserve bounded page metadata", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify([{
      id: 7,
      ticket_id: "ticket /1",
      user_id: "agent-1",
      user_name: "Agent One",
      description: "Paged work",
      minutes: 15,
      entry_date: "2026-08-26T00:00:00Z",
      created_at: "2026-08-26T00:00:00Z",
    }]), {
      status: 200,
      headers: {
        "x-page-limit": "2",
        "x-page-offset": "4",
        "x-has-more": "true",
      },
    });
  };

  try {
    const scoped = await api.getTimeEntries({
      ticketId: "ticket /1",
      userId: "agent & 1",
      teamId: "team/1",
      limit: 2,
      offset: 4,
    });
    const ticket = await api.getTicketTimeEntries("ticket /1", {
      userId: "agent & 1",
      limit: 2,
      offset: 4,
    });

    assert.deepEqual(calls, [
      "/api/time-entries?ticket_id=ticket+%2F1&user_id=agent+%26+1&team_id=team%2F1&limit=2&offset=4",
      "/api/time-entries/ticket/ticket%20%2F1?user_id=agent+%26+1&limit=2&offset=4",
    ]);
    for (const page of [scoped, ticket]) {
      assert.equal(page.entries.length, 1);
      assert.equal(page.limit, 2);
      assert.equal(page.offset, 4);
      assert.equal(page.hasMore, true);
    }
  } finally {
    global.fetch = originalFetch;
  }
});

test("change approval history preserves bounded page metadata", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify([{
      id: 51,
      change_id: "change /1",
      approver_id: null,
      approver_name: null,
      decision: "approved",
      comment: "Retained after account deletion",
      decided_at: "2026-08-26T00:00:00Z",
      created_at: "2026-08-26T00:00:00Z",
    }]), {
      status: 200,
      headers: {
        "x-page-limit": "50",
        "x-page-offset": "50",
        "x-has-more": "true",
      },
    });
  };

  try {
    const page = await api.getChangeApprovals("change /1", { limit: 50, offset: 50 });

    assert.deepEqual(calls, [
      "/api/changes/change%20%2F1/approvals?limit=50&offset=50",
    ]);
    assert.equal(page.approvals.length, 1);
    assert.equal(page.approvals[0].approver_id, null);
    assert.equal(page.limit, 50);
    assert.equal(page.offset, 50);
    assert.equal(page.hasMore, true);
  } finally {
    global.fetch = originalFetch;
  }
});

test("change approval history fails safe when pagination headers are unavailable", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  global.fetch = async () => new Response(JSON.stringify([{
    id: 2,
    change_id: "change-2",
    approver_id: "reviewer-2",
    approver_name: "Reviewer Two",
    decision: null,
    comment: null,
    decided_at: null,
    created_at: "2026-08-26T00:00:00Z",
  }]), { status: 200 });

  try {
    const page = await api.getChangeApprovals("change-2", { limit: 1, offset: 1 });

    assert.equal(page.limit, 1);
    assert.equal(page.offset, 1);
    assert.equal(page.hasMore, true);
  } finally {
    global.fetch = originalFetch;
  }
});

test("survey ticket search encodes complete server-side terminal paging", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: {
        "x-page-limit": "50",
        "x-page-offset": "100",
        "x-has-more": "true",
      },
    });
  };

  try {
    const page = await api.getSurveyEligibleTickets({
      search: "VPN & archived",
      limit: 50,
      offset: 100,
    });

    assert.deepEqual(calls, [
      "/api/surveys/eligible-tickets?limit=50&offset=100&search=VPN+%26+archived",
    ]);
    assert.equal(page.limit, 50);
    assert.equal(page.offset, 100);
    assert.equal(page.hasMore, true);
  } finally {
    global.fetch = originalFetch;
  }
});

test("public survey capabilities stay in POST bodies and never enter request URLs", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  const capability = "private-survey-capability";
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    const responseBody = String(url).endsWith("/lookup")
      ? { question: "How did we do?", expires_at: "2026-09-25T00:00:00Z" }
      : { status: "submitted" };
    return new Response(JSON.stringify(responseBody), { status: String(url).endsWith("/lookup") ? 200 : 201 });
  };

  try {
    await api.lookupPortalSurvey(capability);
    await api.respondPortalSurvey(capability, 5, "Excellent");

    assert.deepEqual(calls.map(({ url }) => url), [
      "/api/portal/survey/lookup",
      "/api/portal/survey/respond",
    ]);
    assert.ok(calls.every(({ url, options }) => options.method === "POST" && !url.includes(capability)));
    assert.deepEqual(JSON.parse(calls[0].options.body), { token: capability });
    assert.deepEqual(JSON.parse(calls[1].options.body), {
      token: capability,
      rating: 5,
      comment: "Excellent",
    });
  } finally {
    global.fetch = originalFetch;
  }
});
