const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadHelpers() {
  const filename = path.join(__dirname, "..", "lib", "analysis-errors.ts");
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  const compile = new Function("exports", "module", output);
  compile(loaded.exports, loaded);
  return loaded.exports;
}

const { analysisErrorDetails, persistedAnalysisErrorDetails } = loadHelpers();

test("partial analysis errors identify the failed artifact and safe cause", () => {
  assert.equal(
    analysisErrorDetails([{ step: "summary", error: "invalid_output" }]),
    "Summary: the provider returned an invalid structured response",
  );
  assert.equal(
    analysisErrorDetails([
      { step: "resolution", error: "provider_unavailable" },
      { step: "refresh", error: "internal_error" },
    ]),
    "Resolution plan: the AI provider was unavailable; Intelligence refresh: an internal processing error occurred",
  );
});

test("persisted failure signatures support new and legacy records without exposing raw values", () => {
  assert.equal(
    persistedAnalysisErrorDetails("summary:invalid_output,refresh:timeout"),
    "Summary: the provider returned an invalid structured response; Intelligence refresh: the step timed out",
  );
  assert.equal(
    persistedAnalysisErrorDetails("summary"),
    "Summary: failed before a safe cause was recorded",
  );
  assert.equal(
    persistedAnalysisErrorDetails("unknown-secret-bearing-value"),
    "AI pipeline: processing failed",
  );
  assert.equal(persistedAnalysisErrorDetails("operator_retry_queue_cleared"), null);
  assert.equal(persistedAnalysisErrorDetails(null), null);
});
