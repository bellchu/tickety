const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("agent routes expose trustworthy loading, identity, and account recovery states", () => {
  const route = read("app", "agent", "page.tsx");
  const roster = read("app", "agents", "page.tsx");

  assert.match(route, /aria-busy="true" aria-label="Loading agent workspace"/);
  assert.match(roster, /const hasIdentitySnapshot = identityLinksQuery\.data !== undefined/);
  assert.match(roster, /disabled=\{!hasIdentitySnapshot\}/);
  assert.match(roster, /is_active: true/);
  assert.match(roster, />Reactivate<\/Button>/);
  assert.match(roster, /type="submit" form=\{formId\}/);
  assert.match(roster, /<form id=\{formId\}/);
  assert.match(roster, /setDirectorySearch\(directorySearchInput\.trim\(\)\), 300/);
  assert.match(roster, /search: directorySearch, limit: 200/);
  assert.match(roster, /externalQuery\.data\?\.has_more/);
});

test("admin status routes distinguish access failures and preserve verified snapshots", () => {
  const overview = read("app", "settings", "status", "page.tsx");
  const ai = read("app", "settings", "ai-status", "page.tsx");
  const sync = read("app", "settings", "sync", "page.tsx");

  assert.match(overview, /Status access could not be checked/);
  assert.match(overview, /const refreshableQueries = \[readinessQuery, versionQuery,/);
  assert.match(overview, /const applicationUnavailable = Boolean\(readinessQuery\.error\)/);
  assert.match(overview, /const buildUnavailable = Boolean\(versionQuery\.error\)/);
  assert.match(overview, /buildUnavailable \? "Unavailable"/);

  assert.match(ai, /AI status access could not be checked/);
  assert.match(ai, /const lastPageOffset = totalTasks === 0/);
  assert.match(ai, /The last verified snapshot remains visible/);
  assert.match(ai, /role="group" aria-label="AI task status views"/);
  assert.match(ai, /aria-pressed=\{view === item\.value\}/);
  assert.doesNotMatch(ai, /role="tab"/);

  assert.match(sync, /Sync access could not be checked/);
  assert.match(sync, /statusQuery\.dataUpdatedAt/);
  assert.match(sync, /last \$\{status\.automatic_fetch_days\} days/);
  assert.match(sync, /disabled=\{syncBusy\}/);
  assert.match(sync, /The last verified provider snapshot remains visible/);
});

test("dense personal and team routes disclose detail without weakening accessibility", () => {
  const leaderboard = read("app", "leaderboard", "page.tsx");
  const profile = read("app", "profile", "page.tsx");

  assert.match(leaderboard, /const VISIBLE_STANDINGS = 10/);
  assert.match(leaderboard, /people\.slice\(0, VISIBLE_STANDINGS\)/);
  assert.match(leaderboard, /Show \{remainingPeople\.length\.toLocaleString\(\)\} more/);
  assert.match(leaderboard, /aria-label=\{`Rank \$\{rank\}`\}/);

  assert.match(profile, /aria-label="Loading recognitions"/);
  assert.match(profile, /aria-hidden="true" className="grid h-16/);
  assert.match(profile, /filter\(\(key\) => ALL_RECOGNITION_KEYS\.includes\(key\)\)/);
  assert.doesNotMatch(profile, /opacity-70/);
  assert.doesNotMatch(profile, /MomentumCounter/);
});

test("ticket creation remains fail-closed when its access check fails", () => {
  const tickets = read("app", "tickets", "page.tsx");

  assert.match(tickets, /const canCreateTicket = !authQuery\.isError && canCreateTickets/);
  assert.match(tickets, /Ticket control access could not be verified/);
  assert.match(tickets, /if \(!canCreateTicket\) setNewTicketOpen\(false\)/);
});
