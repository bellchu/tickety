const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

function loadApi() {
  const filename = path.join(root, "lib", "api.ts");
  const output = ts.transpileModule(read("lib", "api.ts"), {
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

test("problem API preserves filtered totals and global summary headers", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const problem = { id: "problem-1", title: "Recurring VPN outage" };
  global.fetch = async (url) => {
    assert.equal(
      url,
      "/api/problems?status=Known+Error&search=VPN+%26+edge&limit=25&offset=50",
    );
    return new Response(JSON.stringify([problem]), {
      status: 200,
      headers: {
        "x-page-limit": "25",
        "x-page-offset": "50",
        "x-page-total": "88",
        "x-page-has-more": "true",
        "x-problems-total": "123",
        "x-problems-investigating": "12",
        "x-problems-known-errors": "7",
        "x-problems-linked-tickets": "54",
      },
    });
  };

  try {
    assert.deepEqual(await api.getProblemsPage({
      status: "Known Error",
      search: " VPN & edge ",
      limit: 25,
      offset: 50,
    }), {
      problems: [problem],
      limit: 25,
      offset: 50,
      total: 88,
      hasMore: true,
      summary: {
        total: 123,
        investigating: 12,
        knownErrors: 7,
        linkedTickets: 54,
      },
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test("linked problem tickets use bounded response-header pagination", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const ticket = { id: "ticket-1", subject: "VPN disconnect" };
  global.fetch = async (url) => {
    assert.equal(
      url,
      "/api/problems/problem%20%2F1/tickets?limit=50&offset=100",
    );
    return new Response(JSON.stringify([ticket]), {
      status: 200,
      headers: {
        "x-page-limit": "50",
        "x-page-offset": "100",
        "x-has-more": "false",
      },
    });
  };

  try {
    assert.deepEqual(
      await api.getProblemTicketsPage("problem /1", { limit: 50, offset: 100 }),
      { tickets: [ticket], limit: 50, offset: 100, hasMore: false },
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test("problem register and linked tickets preserve loaded pages on later failure", () => {
  const page = read("app", "problems", "page.tsx");
  const api = read("lib", "api.ts");

  assert.doesNotMatch(api, /\bgetProblems:/);
  assert.doesNotMatch(api, /\bgetProblemTickets:/);
  assert.match(api, /getProblemsPage: async/);
  assert.match(api, /getProblemTicketsPage: async/);
  assert.match(api, /x-page-total/);
  assert.match(api, /x-page-has-more/);
  assert.match(api, /x-problems-total/);
  assert.ok((page.match(/useInfiniteQuery/g) || []).length >= 2);
  assert.match(page, /setTimeout\(\(\) => setDebouncedSearch\(search\.trim\(\)\), 300\)/);
  assert.match(page, /api\.getProblemsPage/);
  assert.match(page, /status: statusFilter \|\| undefined/);
  assert.match(page, /search: debouncedSearch \|\| undefined/);
  assert.match(page, /limit: PROBLEM_PAGE_SIZE/);
  assert.match(page, /offset: pageParam/);
  assert.match(page, /const summary = firstPage\?\.summary/);
  assert.doesNotMatch(page, /problems\.filter\(\(item\)/);
  assert.doesNotMatch(page, /problems\.reduce\(/);
  assert.match(page, /problemsQuery\.isError && !filtered\.length/);
  assert.match(page, /problemsQuery\.isFetchNextPageError/);
  assert.match(page, /The problem records already shown remain available/);
  assert.match(page, />Load more problems<\/Button>/);
  assert.match(page, /api\.getProblemTicketsPage/);
  assert.match(page, /limit: PROBLEM_TICKET_PAGE_SIZE/);
  assert.match(page, /ticketsQuery\.data\?\.pages\.flatMap/);
  assert.match(page, /ticketsQuery\.isError && !tickets\.length/);
  assert.match(page, /ticketsQuery\.isFetchNextPageError/);
  assert.match(page, /The linked tickets already shown remain available/);
  assert.match(page, />Load more linked tickets<\/Button>/);
});
