const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

function loadOptionsHelper() {
  const filename = path.join(root, "lib", "ticket-config-options.ts");
  const output = ts.transpileModule(read("lib", "ticket-config-options.ts"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  const compile = new Function("require", "exports", "module", output);
  compile((specifier) => {
    throw new Error(`Unexpected runtime import: ${specifier}`);
  }, loaded.exports, loaded);
  return loaded.exports;
}

test("configured ticket choices follow sort_order and retain configured labels", () => {
  const { ticketStatusOptions, ticketPriorityOptions } = loadOptionsHelper();
  const statuses = ticketStatusOptions([
    { name: "Waiting", label: "Waiting on customer", sort_order: 30 },
    { name: "Investigating", label: "Investigating", sort_order: 10 },
    { name: "Queued", label: "", sort_order: 20 },
  ]);
  const priorities = ticketPriorityOptions([
    { name: "Urgent", label: "Urgent response", sort_order: 2 },
    { name: "Routine", label: "Routine response", sort_order: 1 },
  ]);

  assert.deepEqual(statuses.map(({ value, label }) => ({ value, label })), [
    { value: "Investigating", label: "Investigating" },
    { value: "Queued", label: "Queued" },
    { value: "Waiting", label: "Waiting on customer" },
  ]);
  assert.deepEqual(priorities.map((option) => option.value), ["Routine", "Urgent"]);
});

test("missing config falls back without blocking and P3 is the preferred creation default", () => {
  const {
    defaultTicketPriority,
    ticketCreationPriorityOptions,
    ticketListStatusOptions,
    ticketPriorityOptions,
    ticketStatusOptions,
  } = loadOptionsHelper();
  const fallbackListStatuses = ticketListStatusOptions(undefined);
  const fallbackDetailStatuses = ticketStatusOptions(undefined);
  const fallbackPriorities = ticketPriorityOptions(null);
  const fallbackCreationPriorities = ticketCreationPriorityOptions(undefined);

  assert.deepEqual(fallbackListStatuses.map((option) => option.value), [
    "Open",
    "Escalated",
    "Awaiting Review",
    "Closed",
  ]);
  assert.deepEqual(fallbackDetailStatuses.map((option) => option.value), [
    "New",
    "Open",
    "Awaiting Review",
    "Pending",
    "Escalated",
    "Resolved",
    "Closed",
  ]);
  assert.deepEqual(fallbackPriorities.map((option) => option.value), ["P1", "P2", "P3", "P4"]);
  assert.deepEqual(fallbackCreationPriorities.map((option) => option.value), ["P3", "P2", "P1"]);
  assert.equal(defaultTicketPriority(fallbackCreationPriorities), "P3");
  assert.equal(defaultTicketPriority(ticketPriorityOptions([
    { name: "Routine", label: "Routine", sort_order: 20 },
    { name: "Urgent", label: "Urgent", sort_order: 10 },
  ])), "Urgent");
});

test("legacy values stay selectable while compact status choices remain bounded", () => {
  const {
    preserveTicketConfigValue,
    ticketStatusOptions,
    visibleTicketStatusOptions,
  } = loadOptionsHelper();
  const configured = ticketStatusOptions([
    { name: "One", label: "One", sort_order: 1 },
    { name: "Two", label: "Two", sort_order: 2 },
    { name: "Three", label: "Three", sort_order: 3 },
    { name: "Four", label: "Four", sort_order: 4 },
    { name: "Five", label: "Five", sort_order: 5 },
  ]);

  assert.deepEqual(
    preserveTicketConfigValue(configured, "Legacy").map((option) => option.value),
    ["One", "Two", "Three", "Four", "Five", "Legacy"],
  );
  assert.deepEqual(
    visibleTicketStatusOptions(configured, "Five", 3).map((option) => option.value),
    ["One", "Two", "Three", "Five"],
  );
  assert.deepEqual(
    visibleTicketStatusOptions(configured, "Legacy", 3).map((option) => option.value),
    ["One", "Two", "Three", "Legacy"],
  );
});

test("core ticket surfaces consume shared config choices and expose a labelled composer", () => {
  const list = read("components", "ticket", "TicketList.tsx");
  const modal = read("components", "ticket", "NewTicketModal.tsx");
  const detail = read("app", "tickets", "[id]", "page.tsx");

  for (const source of [list, detail]) {
    assert.match(source, /queryFn: api\.getStatusConfig/);
    assert.match(source, /queryFn: api\.getPriorityConfig/);
    assert.match(source, /preserveTicketConfigValue/);
  }
  assert.match(modal, /queryFn: api\.getPriorityConfig/);
  assert.match(modal, /defaultTicketPriority/);
  assert.match(modal, /priorityWasChanged/);
  assert.match(modal, /const opening = open && !wasOpen\.current/);
  assert.match(list, /visibleTicketStatusOptions/);
  assert.match(list, /statusOptions\.map/);
  assert.match(list, /bulkPriorityOptions\.map/);
  assert.match(list, /const canBulk = !meQuery\.isError && canCreateTickets\(meQuery\.data\)/);
  assert.match(detail, /<label htmlFor="ticket-comment-composer"/);
  assert.match(detail, /<textarea\s+id="ticket-comment-composer"/);
});

test("internal ticket write controls require an authenticated demo administrator", () => {
  const detail = read("app", "tickets", "[id]", "page.tsx");

  assert.match(detail, /import \{ canAccessProtectedIntelligence, canCreateTickets \} from "@\/lib\/auth"/);
  assert.match(detail, /queryKey: \["auth-me"\], queryFn: api\.getAuthMe, retry: false/);
  assert.match(detail, /const canEditInternalTicket = !authQuery\.isError && canCreateTickets\(authQuery\.data\)/);
  assert.match(detail, /<InternalTicketPanel ticket=\{ticket\} \/>/);
  assert.match(
    detail,
    /canEditInternalTicket \? \(\s*<AgentActionPanel ticket=\{ticket\} \/>\s*\) : \(\s*<InternalTicketReadOnlyPanel/,
  );
  assert.match(detail, /function InternalTicketReadOnlyPanel/);
  assert.match(detail, /Internal ticket · Read only/);
  assert.match(detail, /authenticated administrator in the demo environment/);
});
