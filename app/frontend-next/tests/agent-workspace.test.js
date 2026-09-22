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

test("agent queues page through every server result and debounce search input", () => {
  const workspace = source("components/agent/AgentWorkspace.tsx");
  const api = source("lib/api.ts");

  assert.match(workspace, /const AGENT_TICKET_PAGE_SIZE = 25/);
  assert.match(workspace, /useInfiniteQuery\(\{/);
  assert.match(workspace, /queryFn: \(\{ pageParam \}\) => api\.getAgentWorkspaceTickets/);
  assert.match(workspace, /offset: pageParam/);
  assert.match(workspace, /lastPage\.hasMore && lastPage\.tickets\.length > 0/);
  assert.match(workspace, /lastPageParam \+ lastPage\.tickets\.length/);
  assert.match(workspace, /ticketsQuery\.fetchNextPage\(\)/);
  assert.match(workspace, />Load more tickets</);
  assert.match(workspace, /window\.setTimeout\(\(\) => setSearch\(searchInput\.trim\(\)\), 300\)/);
  assert.match(api, /params\.set\("offset", String\(options\.offset\)\)/);
  assert.match(api, /response\.headers\.get\("x-has-more"\) === "true"/);
  assert.match(api, /params\.set\("ticket_id", options\.ticketId\)/);
  assert.match(workspace, /queryKey: \[\s*"agent-workspace",\s*"selected-ticket"/);
  assert.match(workspace, /ticketId: selectedId/);
  assert.match(workspace, /deepLinkedTicketQuery\.isSuccess/);
  assert.match(workspace, /Linked ticket unavailable/);
});

test("agent workspace distinguishes bootstrap failures and retries seen updates without racing or falsely marking success", () => {
  const workspace = source("components/agent/AgentWorkspace.tsx");

  assert.match(workspace, /bootstrapQuery\.isError \? \(/);
  assert.match(workspace, /Agent workspace identity could not be checked/);
  assert.match(workspace, /bootstrapQuery\.data && !bootstrapQuery\.data\.identity/);
  assert.match(workspace, /Freshservice work identity not linked/);
  assert.match(workspace, /markingSeen\.current\.add\(ticketId\)/);
  assert.match(workspace, /api\.updateAgentTicketState\(ticketId, \{ mark_seen: true \}\)/);
  assert.match(workspace, /\.then\(\(\) => \{\s*markedSeen\.current\.add\(ticketId\)/);
  assert.match(workspace, /const MARK_SEEN_RETRY_DELAYS_MS = \[1_000, 3_000, 10_000\] as const/);
  assert.match(workspace, /if \(markedSeen\.current\.has\(ticketId\) \|\| markingSeen\.current\.has\(ticketId\)\) return/);
  assert.match(workspace, /const attempt = markSeenRetryAttempts\.current\.get\(ticketId\) \?\? 0/);
  assert.match(workspace, /const retryTimer = window\.setTimeout\(\(\) => \{\s*markSeenRetryTimers\.current\.delete\(ticketId\);\s*markTicketSeen\(ticketId\);/);
  assert.match(workspace, /const retryTimers = markSeenRetryTimers\.current/);
  assert.match(workspace, /for \(const timer of retryTimers\.values\(\)\) window\.clearTimeout\(timer\)/);
  assert.doesNotMatch(workspace, /\.catch\(\(\) => undefined\)/);
  assert.match(workspace, /\.finally\(\(\) => markingSeen\.current\.delete\(ticketId\)\)/);
  assert.match(workspace, /density="compact" title="Inbox unavailable"/);
  assert.match(workspace, /className="min-h-0 border-0 px-4 py-6 sm:min-h-40 lg:min-h-52" title="This folder is clear"/);
});

test("agent workspace schedules follow-up in local time and keeps state writes recoverable", () => {
  const workspace = source("components/agent/AgentWorkspace.tsx");

  assert.match(workspace, /title="Schedule follow-up"/);
  assert.match(workspace, /Times use your local time zone/);
  assert.match(workspace, /In 2 hours/);
  assert.match(workspace, /Tomorrow, 9:00 AM/);
  assert.match(workspace, /Next workday, 9:00 AM/);
  assert.match(workspace, /value: inTwoHours/);
  assert.match(workspace, /value: \(\) => localDateTimeAt\(1, 9\)/);
  assert.match(workspace, /onSchedule\(preset\.value\(\)\)/);
  assert.match(workspace, /type="datetime-local"/);
  assert.match(workspace, /Choose a future local date and time/);
  assert.match(workspace, /follow_up_at: followUpAt/);
  assert.match(workspace, /action: "follow_up"/);
  assert.match(workspace, /onError: \(error, request\)/);
  assert.match(workspace, /Ticket state was not saved/);
  assert.match(workspace, />Retry</);
  assert.match(workspace, /updateTicketState\(stateFeedback\.request!/);
});

test("agent workspace reports clipboard success and failure without an unhandled copy rejection", () => {
  const workspace = source("components/agent/AgentWorkspace.tsx");

  assert.match(workspace, /try \{\s*await navigator\.clipboard\.writeText\(value\);/);
  assert.match(workspace, /setCopyFeedback\(kind === "link" \? "Ticket link copied\." : "Suggested response copied\."\)/);
  assert.match(workspace, /catch \{\s*setCopyFeedback\("Copy failed\. Select and copy the text manually\."\);/);
  assert.match(workspace, /aria-live="polite"/);
  assert.match(workspace, /role=\{copyFeedback\.startsWith\("Copy failed"\) \? "alert" : undefined\}/);
  assert.match(workspace, /onClick=\{\(\) => void onCopy\(/);
});
