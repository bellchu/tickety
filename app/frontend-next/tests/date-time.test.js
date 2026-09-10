const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadDateTimeHelpers() {
  const filename = path.join(__dirname, "..", "lib", "date-time.ts");
  const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  new Function("exports", "module", output)(loaded.exports, loaded);
  return loaded.exports;
}

const {
  formatLocalDateTime,
  localDateKey,
  parseApiDateTime,
  resolvedLocalTimeZone,
  toLocalDateTimeInput,
} = loadDateTimeHelpers();

test("API datetimes without offsets are interpreted as UTC instants", () => {
  assert.equal(
    parseApiDateTime("2026-01-01T15:20:00").toISOString(),
    "2026-01-01T15:20:00.000Z",
  );
  assert.equal(
    parseApiDateTime("2026-01-01T10:20:00-05:00").toISOString(),
    "2026-01-01T15:20:00.000Z",
  );
  assert.equal(parseApiDateTime("not-a-date"), null);
});

test("display, form values, and export dates follow the user's local time", () => {
  const originalTimeZone = process.env.TZ;
  process.env.TZ = "America/Toronto";
  try {
    const instant = "2026-01-01T15:20:00";
    assert.equal(
      formatLocalDateTime(instant, {
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }),
      "10:20",
    );
    assert.equal(toLocalDateTimeInput(instant), "2026-01-01T10:20");
    assert.equal(localDateKey(new Date("2026-01-01T03:00:00Z")), "2025-12-31");
    assert.equal(resolvedLocalTimeZone(), "America/Toronto");
  } finally {
    if (originalTimeZone === undefined) delete process.env.TZ;
    else process.env.TZ = originalTimeZone;
  }
});

test("invalid and missing values use the caller's fallback", () => {
  assert.equal(formatLocalDateTime(null, undefined, "Not available"), "Not available");
  assert.equal(formatLocalDateTime("invalid", undefined, "Not available"), "Not available");
  assert.equal(toLocalDateTimeInput("invalid"), "");
});
