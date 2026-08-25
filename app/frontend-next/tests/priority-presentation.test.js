const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("ticket detail highlights content priority with stars and renders sentiment as emoji", () => {
  const strip = read("components", "ticket", "TicketSignalStrip.tsx");
  const intelligence = read("lib", "ticket-intelligence.ts");

  assert.match(strip, /Content intelligence/);
  assert.match(strip, /rating\.visual === "emoji"/);
  assert.match(strip, /rating\.visual === "meter"/);
  assert.match(strip, /rating\.visual === "risk"/);
  assert.match(strip, /<Star/);
  assert.match(strip, /rating\.highlighted/);
  assert.match(intelligence, /label: "Content priority"/);
  assert.match(intelligence, /label: "Sentiment sensor"/);
  assert.match(intelligence, /😡/u);
  assert.match(intelligence, /😊/u);
});

test("primary agent ticket views use the shared priority and sentiment indicator", () => {
  const indicator = read("components", "ticket", "TicketPriorityIndicator.tsx");
  const ticketList = read("components", "ticket", "TicketList.tsx");
  const dashboard = read("app", "page.tsx");
  const workspace = read("components", "agent", "AgentWorkspace.tsx");

  assert.match(indicator, /AI-assessed|prioritySignal/);
  assert.match(indicator, /Customer sentiment:/);
  assert.match(indicator, /Reported \$\{reportedPriority\}/);
  assert.match(ticketList, /TicketPriorityIndicator/);
  assert.match(dashboard, /TicketPriorityIndicator/);
  assert.match(workspace, /TicketPriorityIndicator/);
});
