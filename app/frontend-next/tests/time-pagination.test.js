const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("time entry API clients expose bounded response-header pagination", () => {
  const api = read("lib", "api.ts");
  const types = read("lib", "types.ts");

  assert.match(types, /export interface TimeEntryPage/);
  assert.ok((api.match(/fetchAPIResponse<import\("\.\/types"\)\.TimeEntry\[\]>/g) || []).length >= 2);
  assert.ok((api.match(/response\.headers\.get\("x-page-limit"\)/g) || []).length >= 2);
  assert.ok((api.match(/response\.headers\.get\("x-page-offset"\)/g) || []).length >= 2);
  assert.ok((api.match(/response\.headers\.get\("x-has-more"\) === "true"/g) || []).length >= 2);
  assert.match(api, /encodeURIComponent\(ticketId\)/);
});

test("time page keeps each view bounded and exposes explicit pagination", () => {
  const page = read("app", "time", "page.tsx");

  assert.match(page, /const TIME_ENTRY_PAGE_SIZE = 25/);
  assert.match(page, /const \[entryOffset, setEntryOffset\] = useState\(0\)/);
  assert.match(page, /limit: TIME_ENTRY_PAGE_SIZE/);
  assert.match(page, /offset: entryOffset/);
  assert.match(page, /entriesQuery\.data\?\.entries \?\? \[\]/);
  assert.match(page, /aria-label="Time entry pagination"/);
  assert.match(page, />Previous<\/Button>/);
  assert.match(page, />Next<\/Button>/);
  assert.match(page, /setTicketFilter\(event\.target\.value\); setEntryOffset\(0\)/);
});
