const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const settings = fs.readFileSync(path.join(__dirname, "..", "app", "settings", "page.tsx"), "utf8");

test("ticket taxonomy controls inherit verified administrator access and fail closed", () => {
  assert.match(settings, /<StatusConfigSection canManage=\{canAccessSettings\} \/>/);
  assert.match(settings, /<PriorityConfigSection canManage=\{canAccessSettings\} \/>/);
  assert.ok((settings.match(/enabled: canManage/g) || []).length >= 2);
  assert.ok((settings.match(/!canManage \|\| \[[^\]]+\]\.some\(isConfigurationAccessError\)/g) || []).length >= 2);
  assert.match(settings, /Status configuration access could not be verified/);
  assert.match(settings, /Priority configuration access could not be verified/);
});

test("status lifecycle is mutually exclusive and color choices are bounded", () => {
  for (const color of ["slate", "blue", "amber", "red", "moss", "clay"]) {
    assert.match(settings, new RegExp(`value: "${color}"`));
  }
  assert.match(settings, /type StatusLifecycle = "open" \| "terminal"/);
  assert.match(settings, /is_open: lifecycle === "open"/);
  assert.match(settings, /is_terminal: lifecycle === "terminal"/);
  assert.match(settings, /name="status-lifecycle"/);
  assert.doesNotMatch(settings, /Counts as open/);
  assert.doesNotMatch(settings, /Terminal \(closed\/resolved\)/);
  assert.doesNotMatch(settings, /`bg-\$\{/);
});

test("priority and taxonomy inputs enforce the agreed semantic bounds", () => {
  assert.match(settings, /const CONFIG_NAME_MAX_LENGTH = 100/);
  assert.match(settings, /const PRIORITY_NAME_MAX_LENGTH = 32/);
  assert.match(settings, /const CONFIG_LABEL_MAX_LENGTH = 100/);
  assert.match(settings, /const CONFIG_SORT_ORDER_MAX = 10_000/);
  assert.match(settings, /const PRIORITY_SLA_MIN_HOURS = 1/);
  assert.match(settings, /const PRIORITY_SLA_MAX_HOURS = 8_760/);
  assert.match(settings, /const PRIORITY_WEIGHT_MIN = 1/);
  assert.match(settings, /const PRIORITY_WEIGHT_MAX = 1_000/);
  assert.match(settings, /sort_order: nextConfigSortOrder\(statuses\)/);
  assert.match(settings, /sort_order: nextConfigSortOrder\(priorities\)/);
  assert.match(settings, /lower values rank as more urgent/);
});

test("taxonomy requests expose loading, retry, empty, mutation error, and confirmed deletion states", () => {
  for (const marker of [
    "Loading ticket statuses",
    "Ticket statuses could not be loaded",
    "No ticket statuses configured",
    "Status could not be created",
    "Status could not be removed",
    "Loading ticket priorities",
    "Ticket priorities could not be loaded",
    "No ticket priorities configured",
    "Priority could not be created",
    "Priority could not be removed",
  ]) {
    assert.match(settings, new RegExp(marker));
  }
  assert.match(settings, /title="Remove ticket status\?"/);
  assert.match(settings, /title="Remove ticket priority\?"/);
  assert.match(settings, /aria-label=\{`Remove status \$\{status\.label\}`\}/);
  assert.match(settings, /aria-label=\{`Remove priority \$\{priority\.label\}`\}/);
  assert.match(settings, /grid grid-cols-1 gap-4 sm:grid-cols-2/);
  assert.match(settings, /flex flex-col-reverse gap-2 xs:flex-row xs:justify-end/);
});
