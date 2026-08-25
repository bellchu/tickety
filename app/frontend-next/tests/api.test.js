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
