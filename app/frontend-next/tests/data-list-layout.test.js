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
  assert.match(dataList, /whitespace-normal break-words/);
  assert.doesNotMatch(dataList, /line-clamp|truncate/);
  assert.match(dataList, /min-w-0 rounded-xl/);

  assert.match(badge, /max-w-full/);
  assert.match(badge, /title=\{title \?\?/);
  assert.match(badge, /whitespace-normal break-words/);
  assert.doesNotMatch(badge, /truncate|whitespace-nowrap/);
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
  assert.match(ticketList, /<table className="table-fixed text-left \[&_td\]:align-top \[&_td\]:whitespace-normal/);
  assert.match(ticketList, /style=\{\{ width: tableWidth, minWidth: "100%" \}\}/);
  assert.match(ticketList, /COLUMN_WIDTHS_KEY = "tickety\.ticket-queue\.column-widths\.v3"/);
  assert.match(ticketList, /<TicketPriorityIndicator ticket=\{ticket\}/);
  assert.match(ticketList, /<TicketSentimentSubtitle ticket=\{ticket\}/);
  assert.match(ticketList, /grid grid-cols-1 gap-3[^\n]+sm:grid-cols-2/);
  assert.doesNotMatch(ticketList, /TimelineValue[\s\S]{0,500}whitespace-nowrap/);
  assert.match(dashboard, /<table className="w-full table-fixed text-left \[&_td\]:align-top \[&_td\]:whitespace-normal/);
  assert.match(dashboard, /text=\{ticket\.subject\} lines=\{2\}/);
  assert.match(dashboard, /xl:hidden/);
});

test("report charts allocate multi-line labels outside the plotting area", () => {
  const reports = read("app", "reports", "page.tsx");
  const pageLayout = read("components", "layout", "PageLayout.tsx");

  assert.match(reports, /function wrapChartLabel/);
  assert.match(reports, /function categoryChartHeight/);
  assert.match(reports, /tick=\{<WrappedYAxisTick \/>\}/);
  assert.match(reports, /label="Ticket category legend"/);
  assert.match(reports, /label="Custom report legend"/);
  assert.ok((reports.match(/isAnimationActive=\{false\}/g) || []).length >= 4);
  assert.doesNotMatch(reports, /<Legend/);
  assert.match(reports, /<PageFrame width="wide">/);
  assert.match(pageLayout, /mx-auto min-w-0 w-full/);
});

test("report builder exposes distinct outputs, groupings, and shared criteria", () => {
  const reports = read("app", "reports", "page.tsx");
  const api = read("lib", "api.ts");

  for (const label of [
    "Operational overview",
    "Ticket volume trend",
    "Ticket breakdown",
    "Resolution performance",
    "SLA performance",
  ]) {
    assert.match(reports, new RegExp(label));
  }
  for (const grouping of ["status", "priority", "category", "assignee", "source", "ticket_type"]) {
    assert.match(reports, new RegExp(`\\["${grouping}",`));
  }
  for (const criterion of ["assigneeId", "source", "ticketType", "resolutionState", "slaState"]) {
    assert.match(reports, new RegExp(criterion));
  }
  assert.match(reports, /Generate report/);
  assert.match(api, /getReportSeries/);
  assert.match(api, /downloadReportCsv/);
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

test("settings use accessible tabs and a server-paginated external directory", () => {
  const settings = read("app", "settings", "page.tsx");

  assert.match(settings, /role="tablist" aria-label="Settings sections"/);
  assert.match(settings, /role="tab"/);
  assert.match(settings, /role="tabpanel"/);
  assert.match(settings, /aria-controls=\{`settings-panel-/);
  assert.match(settings, /settingsTabFromHash/);
  assert.match(settings, /activeTab === "integrations"/);

  assert.match(settings, /api\.getExternalUsers\(\{ search, userType, limit: pageSize, offset \}\)/);
  assert.match(settings, /Search name, email, title, or provider ID/);
  assert.match(settings, /All identities/);
  assert.match(settings, /External ITSM directory pagination/);
  assert.match(settings, /\[25, 50, 100\]/);
  assert.doesNotMatch(settings, /users\.slice\(/);
});
