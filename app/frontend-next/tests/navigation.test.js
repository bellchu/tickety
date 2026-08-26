const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadNavigationHelpers() {
  const filename = path.join(__dirname, "..", "lib", "navigation.ts");
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

const {
  getCurrentNavigationItem,
  isNavigationItemActive,
  navigationSections,
} = loadNavigationHelpers();

test("workspace navigation stays within four directly scannable sections", () => {
  assert.deepEqual(
    navigationSections.map((section) => section.label),
    ["Work", "Operations", "Team", "Insights"],
  );
  assert.deepEqual(
    navigationSections[0].items.map((item) => item.href),
    ["/", "/agent", "/tickets", "/time"],
  );
  assert.ok(
    navigationSections.every((section) => section.items.length <= 5),
    "sections should remain short enough to scan without disclosure controls",
  );
});

test("navigation destinations are unique and remain directly reachable", () => {
  const items = navigationSections.flatMap((section) => section.items);
  const hrefs = items.map((item) => item.href);
  assert.equal(new Set(hrefs).size, hrefs.length);
  assert.equal(items.length, 15);
  assert.ok(items.every((item) => item.href.startsWith("/")));
});

test("active navigation matches exact and nested routes without prefix collisions", () => {
  assert.equal(isNavigationItemActive("/", "/"), true);
  assert.equal(isNavigationItemActive("/tickets/123", "/tickets"), true);
  assert.equal(isNavigationItemActive("/tickets-archive", "/tickets"), false);
  assert.equal(isNavigationItemActive("/reports", "/"), false);
});

test("mobile context labels cover nested and utility routes", () => {
  assert.equal(getCurrentNavigationItem("/tickets/123")?.label, "All Tickets");
  assert.equal(getCurrentNavigationItem("/agent")?.label, "Agent");
  assert.equal(getCurrentNavigationItem("/email")?.label, "Email");
  assert.equal(getCurrentNavigationItem("/intelligence")?.label, "OPS Tower");
  assert.equal(getCurrentNavigationItem("/settings/security")?.label, "Settings");
  assert.equal(getCurrentNavigationItem("/settings/status/ai")?.label, "Status");
  assert.equal(getCurrentNavigationItem("/profile")?.label, "My profile");
  assert.equal(getCurrentNavigationItem("/unknown"), undefined);
});
