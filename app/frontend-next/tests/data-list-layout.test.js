const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("shared list primitives keep long values visible and tables navigable", () => {
  const dataList = read("components", "ui", "DataList.tsx");
  const badge = read("components", "ui", "Badge.tsx");

  assert.match(dataList, /role="region"/);
  assert.match(dataList, /tabIndex=\{0\}/);
  assert.match(dataList, /overflow-x-auto overscroll-x-contain/);
  assert.match(dataList, /w-full table-fixed/);
  assert.match(dataList, /title=\{text\}/);
  assert.match(dataList, /\[overflow-wrap:anywhere\]/);
  assert.match(dataList, /line-clamp-2/);
  assert.match(dataList, /min-w-0 rounded-xl/);

  assert.match(badge, /max-w-full/);
  assert.match(badge, /title=\{title \?\?/);
  assert.match(badge, /min-w-0 truncate/);
});

test("data-heavy pages pair bounded desktop tables with mobile cards", () => {
  const pages = [
    "agents",
    "assets",
    "changes",
    "problems",
    "services",
    "settings",
    "surveys",
    "time",
  ];

  for (const page of pages) {
    const source = read("app", page, "page.tsx");
    assert.match(source, /DataTableViewport/, `${page} uses the accessible table viewport`);
    assert.match(source, /<DataTable(?: className="min-w-\[[^"]+\]")?>/, `${page} uses the shared fixed-layout table`);
    assert.match(source, /md:hidden/, `${page} supplies a narrow-screen layout`);
    assert.match(source, /ListText/, `${page} protects user-provided text`);
  }
});

test("ticket queues preserve hierarchy without hiding routing or requester values", () => {
  const ticketList = read("components", "ticket", "TicketList.tsx");
  const dashboard = read("app", "page.tsx");

  assert.match(ticketList, /DataListCard/);
  assert.match(ticketList, /text=\{routingLabel\(ticket\)\} lines="wrap"/);
  assert.match(ticketList, /text=\{requesterName\(ticket\)\} lines=\{2\}/);
  assert.match(ticketList, /<table className="table-fixed text-left" style=\{\{ width: tableWidth \}\}>/);
  assert.match(dashboard, /<table className="w-full table-fixed text-left">/);
  assert.match(dashboard, /text=\{ticket\.subject\} lines=\{2\}/);
  assert.match(dashboard, /xl:hidden/);
});

test("secondary lists safely wrap external and AI-generated content", () => {
  const files = [
    ["app", "intelligence", "page.tsx"],
    ["app", "knowledge", "page.tsx"],
    ["app", "leaderboard", "page.tsx"],
    ["app", "settings", "ai-status", "page.tsx"],
    ["app", "tickets", "[id]", "page.tsx"],
  ];

  for (const parts of files) {
    assert.match(read(...parts), /ListText/, `${parts.join("/")} uses safe multi-line text`);
  }

  assert.match(read("components", "engagement", "ReasoningLog.tsx"), /\[overflow-wrap:anywhere\]/);
  assert.match(read("app", "portal", "page.tsx"), /\[overflow-wrap:anywhere\]/);
  assert.match(read("app", "settings", "sync", "page.tsx"), /\[overflow-wrap:anywhere\]/);
});
