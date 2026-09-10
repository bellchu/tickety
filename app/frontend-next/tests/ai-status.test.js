const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadHelpers() {
  const filename = path.join(__dirname, "..", "lib", "ai-status.ts");
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  new Function("exports", "module", output)(loaded.exports, loaded);
  return loaded.exports;
}

const {
  aiArtifactLabel,
  aiCallStatusMeta,
  aiTaskLifecycleMeta,
  aiTaskStatusMeta,
  canRetryAITask,
  operationalCodeLabel,
  safetyWithheldArtifacts,
} = loadHelpers();

test("AI task lifecycle metadata covers every durable status with an operator label", () => {
  const states = [
    "not_analyzed",
    "queued",
    "retry_scheduled",
    "running",
    "lease_expired",
    "completed",
    "partial",
    "stale",
    "failed",
    "dead_letter",
    "paused",
    "unknown",
  ];
  for (const state of states) {
    const metadata = aiTaskLifecycleMeta(state);
    assert.ok(metadata.label);
    assert.ok(metadata.description);
    assert.ok(["neutral", "info", "success", "warning", "danger"].includes(metadata.variant));
  }
  assert.equal(aiTaskLifecycleMeta("lease_expired").variant, "danger");
  assert.equal(aiTaskLifecycleMeta("completed").variant, "success");
});

test("artifact and provider call labels turn internal codes into readable operations", () => {
  assert.equal(aiArtifactLabel("resolution"), "Resolution plan");
  assert.equal(aiArtifactLabel("refresh"), "Search index refresh");
  assert.deepEqual(aiCallStatusMeta("attempt_failed"), { label: "Attempt failed", variant: "warning" });
  assert.equal(
    operationalCodeLabel("triage:provider_capacity,resolution:timeout"),
    "triage: provider capacity · resolution: timeout",
  );
  assert.equal(operationalCodeLabel(null), "None");
});

test("single-ticket retry controls recover exhausted work without admitting empty tasks", () => {
  for (const lifecycle of ["retry_scheduled", "paused", "failed", "dead_letter"]) {
    assert.equal(canRetryAITask({ lifecycle, requested_artifacts: ["route"] }), true);
  }
  assert.equal(canRetryAITask({ lifecycle: "completed", requested_artifacts: ["route"] }), false);
  assert.equal(canRetryAITask({ lifecycle: "dead_letter", requested_artifacts: [] }), false);
});

test("completed tasks with terminal safety outcomes never claim every artifact succeeded", () => {
  const task = { lifecycle: "completed", error_code: "resolution:unsafe_output" };
  assert.deepEqual(safetyWithheldArtifacts(task), ["resolution"]);
  assert.deepEqual(aiTaskStatusMeta(task), {
    label: "Safety withheld",
    description: "Unsafe or policy-blocked output was withheld. Safe completed artifacts remain available, and this task will not retry automatically.",
    variant: "warning",
  });
  assert.deepEqual(
    safetyWithheldArtifacts({ lifecycle: "completed", error_code: "summary:content_filtered,route:timeout" }),
    ["summary"],
  );
  assert.equal(aiTaskStatusMeta({ lifecycle: "completed", error_code: null }).label, "Completed");
});
