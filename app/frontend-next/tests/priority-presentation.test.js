const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("content intelligence uses one star language and excludes sentiment cards", () => {
  const strip = read("components", "ticket", "TicketSignalStrip.tsx");
  const intelligence = read("lib", "ticket-intelligence.ts");

  assert.match(strip, /Content intelligence/);
  assert.match(strip, /data-signal-visual="stars"/);
  assert.match(strip, /<Star/);
  assert.match(strip, /rating\.highlighted/);
  assert.doesNotMatch(strip, /emoji|meter|risk.*width|transition-\[width\]/);
  assert.match(intelligence, /label: "Content priority"/);
  assert.doesNotMatch(intelligence, /key: "customer-sentiment"|label: "Sentiment sensor"/);
});

test("sentiment is a plain emoji subtitle immediately after ticket subjects", () => {
  const subtitle = read("components", "ticket", "TicketSentimentSubtitle.tsx");
  const detail = read("app", "tickets", "[id]", "page.tsx");
  const ticketList = read("components", "ticket", "TicketList.tsx");
  const dashboard = read("app", "page.tsx");
  const workspace = read("components", "agent", "AgentWorkspace.tsx");
  const intelligence = read("lib", "ticket-intelligence.ts");

  assert.match(subtitle, /ticketSentimentPresentation/);
  assert.match(subtitle, /Sentiment ·/);
  assert.doesNotMatch(subtitle, /rounded|border|bg-/);
  assert.match(detail, /<\/h1>\s*<TicketSentimentSubtitle ticket=\{ticket\} latestAnalysis=\{latestAnalysis\}/);
  assert.match(ticketList, /ticket\.subject[\s\S]{0,240}<TicketSentimentSubtitle ticket=\{ticket\}/);
  assert.match(dashboard, /ticket\.subject[\s\S]{0,240}<TicketSentimentSubtitle ticket=\{ticket\}/);
  assert.match(workspace, />\{ticket\.subject\}<\/h3>\s*<TicketSentimentSubtitle ticket=\{ticket\}/);
  assert.match(intelligence, /😡/u);
  assert.match(intelligence, /😊/u);
});

test("primary ticket views keep sentiment out of the priority indicator", () => {
  const indicator = read("components", "ticket", "TicketPriorityIndicator.tsx");
  const ticketList = read("components", "ticket", "TicketList.tsx");
  const dashboard = read("app", "page.tsx");
  const workspace = read("components", "agent", "AgentWorkspace.tsx");

  assert.match(indicator, /AI-assessed|prioritySignal/);
  assert.doesNotMatch(indicator, /sentiment|moodEmoji|moodLabel|moodUrgencyColor/i);
  assert.match(indicator, /Reported \$\{reportedPriority\}/);
  assert.match(ticketList, /TicketPriorityIndicator/);
  assert.match(dashboard, /TicketPriorityIndicator/);
  assert.match(workspace, /TicketPriorityIndicator/);
});
