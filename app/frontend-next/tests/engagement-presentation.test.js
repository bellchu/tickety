const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("engagement announcements are separate, polite, and share a layout-relative stack", () => {
  const experience = read("components", "layout", "AppExperience.tsx");
  const points = read("components", "engagement", "SuccessBurst.tsx");
  const recognition = read("components", "engagement", "RecognitionToast.tsx");

  assert.match(experience, /showRecognitionToast/);
  assert.match(experience, /onClose=\{clearRecognitionToast\}/);
  assert.match(experience, /fixed inset-x-4 bottom-4 z-50 flex flex-col gap-3/);
  assert.ok(experience.indexOf("<RecognitionToast") < experience.indexOf("<SuccessBurst"), "recognitions are stacked above points");
  assert.match(points, /<button[\s\S]*<div role="status" aria-live="polite" aria-atomic="true" className="min-w-0">/);
  assert.match(recognition, /<button[\s\S]*<div role="status" aria-live="polite" aria-atomic="true" className="min-w-0">/);
  assert.doesNotMatch(points, /\bfixed\b|\bbottom-/);
  assert.doesNotMatch(recognition, /\bfixed\b|\bbottom-/);
});
