const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

function source(relativePath) {
  return fs.readFileSync(path.join(__dirname, "..", relativePath), "utf8");
}

test("agent workspace exposes the focus folders and provider team inboxes", () => {
  const workspace = source("components/agent/AgentWorkspace.tsx");
  for (const label of ["My Inbox", "Needs reply", "SLA at risk", "Starred", "Follow up", "Team inboxes"]) {
    assert.match(workspace, new RegExp(label));
  }
  assert.match(workspace, /Next best action/);
  assert.match(workspace, /Freshservice work identity not linked/);
});

test("the comprehensive directory is consistently named All Tickets", () => {
  assert.match(source("lib/navigation.ts"), /label: "All Tickets"/);
  assert.match(source("components/ticket/TicketList.tsx"), /title="All Tickets"/);
  assert.match(source("components/agent/AgentWorkspace.tsx"), />\s*All Tickets/);
});
