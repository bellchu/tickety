const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("the one-time portal link can only be dismissed through explicit confirmation", () => {
  const portal = read("app", "portal", "page.tsx");
  const dialog = read("components", "ui", "Dialog.tsx");

  assert.match(portal, /role="alertdialog"/);
  assert.match(portal, /dismissible=\{false\}/);
  assert.match(portal, /closeOnBackdrop=\{false\}/);
  assert.match(portal, /I have saved the link/);
  assert.match(dialog, /\{dismissible && \([\s\S]*?<IconButton/);
  assert.doesNotMatch(dialog, /disabled=\{!dismissible\}/);
});

test("ticket and conversation defaults bound initial information density", () => {
  const tickets = read("components", "ticket", "TicketList.tsx");
  const conversation = read("components", "ticket", "FreshserviceConversationThread.tsx");

  assert.match(tickets, /const PAGE_SIZES = \[10, 25, 50, 100\]/);
  assert.match(tickets, /useState\(10\)/);
  assert.equal((tickets.match(/builtIn: true/g) || []).length, 4);
  assert.equal((tickets.match(/limit: 10, builtIn: true/g) || []).length, 4);
  assert.match(tickets, /<details className="mt-3 border-t border-linen-300 pt-3">/);
  assert.match(tickets, /More ticket details/);
  assert.match(conversation, /const COMMENT_PAGE_SIZE = 25/);
  assert.match(conversation, /lastPage\.length === COMMENT_PAGE_SIZE/);
  assert.match(conversation, /lastPageParam \+ COMMENT_PAGE_SIZE/);
});

test("reports and intelligence progressively disclose supporting controls and panels", () => {
  const reports = read("app", "reports", "page.tsx");
  const intelligence = read("app", "intelligence", "page.tsx");

  assert.match(reports, /aria-label="Applied report criteria"/);
  assert.match(reports, />Refine report</);
  assert.match(reports, /<details className="group rounded-xl/);
  assert.match(reports, /Optional ticket filters/);
  assert.match(reports, /Generate report/);

  for (const marker of ["service-assurance", "team-capacity", "demand-patterns", "automation-discovery"]) {
    assert.match(intelligence, new RegExp(`<details data-intelligence-section="${marker}"`));
  }
  assert.ok((intelligence.match(/density="compact"/g) || []).length >= 3);
  assert.match(intelligence, /aria-label="Supporting intelligence views"/);
});

test("email delays directory search and collapses large recipient selections", () => {
  const email = read("app", "email", "page.tsx");

  assert.match(email, /setDirectorySearch\(search\.trim\(\)\), 300/);
  assert.match(email, /selected\.slice\(0, 6\)/);
  assert.match(email, /selected\.slice\(6\)/);
  assert.match(email, /more recipient/);
});
