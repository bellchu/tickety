const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function transpile(filename) {
  return ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
}

function loadUtils() {
  const libDir = path.join(__dirname, "..", "lib");
  const dateTimeModule = { exports: {} };
  new Function("exports", "module", transpile(path.join(libDir, "date-time.ts")))(
    dateTimeModule.exports,
    dateTimeModule,
  );

  const utilsModule = { exports: {} };
  new Function("require", "exports", "module", transpile(path.join(libDir, "utils.ts")))(
    (specifier) => specifier === "./date-time" ? dateTimeModule.exports : require(specifier),
    utilsModule.exports,
    utilsModule,
  );
  return utilsModule.exports;
}

test("relative times also show the actual timestamp in the user's local time zone", () => {
  const originalTimeZone = process.env.TZ;
  process.env.TZ = "America/Toronto";
  try {
    const { formatTimeAgo } = loadUtils();
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60_000 - 5_000).toISOString();
    const formatted = formatTimeAgo(fiveMinutesAgo);

    assert.match(formatted, /^5m ago · /);
    assert.match(formatted, /(?:EST|EDT)$/);
    assert.match(formatted, /\d{1,2}:\d{2}/);
  } finally {
    if (originalTimeZone === undefined) delete process.env.TZ;
    else process.env.TZ = originalTimeZone;
  }
});
