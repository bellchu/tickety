const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const overviewSource = fs.readFileSync(
  path.join(__dirname, "..", "app", "page.tsx"),
  "utf8",
);

test("overview keeps a decision-first source order with a linked lead queue item", () => {
  const pulse = overviewSource.indexOf('data-overview-section="operational-pulse"');
  const nextAction = overviewSource.indexOf('data-overview-section="next-action"');
  const priorityQueue = overviewSource.indexOf('data-overview-section="priority-queue"');
  const workloadContext = overviewSource.indexOf('data-overview-section="workload-context"');

  assert.ok(pulse >= 0, "operational pulse marker is present");
  assert.ok(nextAction > pulse, "next action follows the operational pulse");
  assert.ok(priorityQueue > nextAction, "next action precedes the queue in source order");
  assert.ok(workloadContext > priorityQueue, "workload context follows the queue in source order");

  assert.equal(
    overviewSource.match(/id="priority-recommendation-summary"/g)?.length,
    1,
    "the recommendation description id is unique",
  );
  assert.ok(
    (overviewSource.match(/aria-describedby=\{index === 0 \? "priority-recommendation-summary"/g)?.length ?? 0) >= 2,
    "mobile and desktop lead rows reference the shared recommendation",
  );
});

test("overview uses an adaptive decision grid and one lower-weight context surface", () => {
  assert.match(overviewSource, /xl:col-start-2 xl:row-start-1/);
  assert.match(overviewSource, /xl:col-start-1 xl:row-span-2 xl:row-start-1/);
  assert.match(overviewSource, /xl:col-start-2 xl:row-start-2/);
  assert.doesNotMatch(overviewSource, /SummaryStrip label="Supporting operations metrics"/);
  assert.doesNotMatch(overviewSource, /function MetricCard/);
  assert.match(overviewSource, /tickety-accent absolute inset-x-0 top-0 h-\[3px\]/);
});

test("overview keeps protected intelligence fail-closed before rendering it", () => {
  assert.match(
    overviewSource,
    /const priorityData = canUseIntelligence && !priorityQuery\.isError \? priorityQuery\.data : undefined/,
  );
  assert.match(
    overviewSource,
    /const slaData = canUseIntelligence && !slaQuery\.isError \? slaQuery\.data : undefined/,
  );
  assert.match(
    overviewSource,
    /usesIntelligenceQueue \? rankedQueue : selectDeterministicQueue\(tickets, 6\)/,
  );
});

test("overview uses complete server totals and a server-generated export", () => {
  assert.match(overviewSource, /api\.getDashboardSummary/);
  assert.match(overviewSource, /api\.getTicketsPage\(\{ sort: "queue", limit: 100 \}\)/);
  assert.match(overviewSource, /api\.downloadReportCsv/);
  assert.doesNotMatch(overviewSource, /function exportTickets/);
  assert.match(overviewSource, /index >= 4 && "hidden sm:block"/);
});
