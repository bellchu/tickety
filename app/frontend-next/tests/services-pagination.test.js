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

test("service APIs encode filters and retain bounded page and global-summary metadata", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url) => {
    calls.push(String(url));
    if (String(url).startsWith("/api/services?")) {
      return new Response(JSON.stringify([{ id: "svc-1", name: "VPN access" }]), {
        status: 200,
        headers: {
          "x-page-limit": "25",
          "x-page-offset": "50",
          "x-has-more": "true",
          "x-service-total": "71",
          "x-service-active": "64",
          "x-service-category-count": "4",
          "x-service-category-options": JSON.stringify(["Access", "Network", "bad\0value", 42]),
          "x-service-category-options-truncated": "true",
        },
      });
    }
    return new Response(JSON.stringify([{ id: "sr-1", ticket_id: "ticket-1" }]), {
      status: 200,
      headers: {
        "x-page-limit": "10",
        "x-page-offset": "20",
        "x-has-more": "false",
        "x-service-request-total": "33",
        "x-service-request-open": "12",
        "x-service-request-pending": "9",
        "x-service-request-pending-approval": "5",
        "x-service-request-awaiting-fulfillment": "4",
      },
    });
  };

  try {
    const services = await api.getServicesPage({
      category: "Network & Access",
      search: " VPN_100% ",
      isActive: true,
      limit: 25,
      offset: 50,
    });
    const requests = await api.getServiceRequestsPage({
      search: " ticket / 1 ",
      serviceItemId: "svc & 1",
      approvalStatus: "pending",
      fulfillmentStatus: "pending",
      limit: 10,
      offset: 20,
    });

    assert.deepEqual(calls, [
      "/api/services?category=Network+%26+Access&search=VPN_100%25&is_active=true&limit=25&offset=50",
      "/api/service-requests?search=ticket+%2F+1&service_item_id=svc+%26+1&approval_status=pending&fulfillment_status=pending&limit=10&offset=20",
    ]);
    assert.deepEqual(services, {
      services: [{ id: "svc-1", name: "VPN access" }],
      limit: 25,
      offset: 50,
      hasMore: true,
      summary: {
        total: 71,
        active: 64,
        categoryCount: 4,
        categoryOptions: ["Access", "Network"],
        categoryOptionsTruncated: true,
      },
    });
    assert.deepEqual(requests, {
      requests: [{ id: "sr-1", ticket_id: "ticket-1" }],
      limit: 10,
      offset: 20,
      hasMore: false,
      summary: {
        total: 33,
        open: 12,
        pending: 9,
        pendingApproval: 5,
        awaitingFulfillment: 4,
      },
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test("service workspace pages on the server and preserves loaded results after later failures", () => {
  const page = read("app", "services", "page.tsx");
  const dashboard = read("app", "page.tsx");
  const api = read("lib", "api.ts");

  assert.match(api, /getServicesPage: async/);
  assert.match(api, /getServiceRequestsPage: async/);
  assert.doesNotMatch(api, /\bgetServices:/);
  assert.doesNotMatch(api, /\bgetServiceRequests:/);
  assert.match(page, /const servicesQuery = useInfiniteQuery/);
  assert.match(page, /const requestsQuery = useInfiniteQuery/);
  assert.match(page, /pages\.flatMap\(\(page\) => page\.services\)/);
  assert.match(page, /pages\.flatMap\(\(page\) => page\.requests\)/);
  assert.match(page, /servicesQuery\.isFetchNextPageError/);
  assert.match(page, /requestsQuery\.isFetchNextPageError/);
  assert.match(page, /The catalog entries already shown remain available/);
  assert.match(page, /The requests already shown remain available/);
  assert.match(page, /service \? null : undefined/);
  assert.match(page, /description: form\.description\.trim\(\)/);
  assert.match(page, /sla_hours: form\.sla_hours \? Number\(form\.sla_hours\) : service \? null : undefined/);
  assert.match(dashboard, /getServicesPage\(\{ isActive: true, limit: 1 \}\)/);
  assert.match(dashboard, /getServiceRequestsPage\(\{ limit: 1 \}\)/);
  assert.match(dashboard, /servicesQuery\.data\?\.summary\.active/);
  assert.match(dashboard, /serviceRequestsQuery\.data\?\.summary\.open/);
});
