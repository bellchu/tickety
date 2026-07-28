const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadAuthHelpers() {
  const filename = path.join(__dirname, "..", "lib", "auth.ts");
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
  canAccessAdministration,
  canAccessProtectedIntelligence,
  hasProtectedProductionSession,
  isDemoContext,
  isDemoAdministrationContext,
} = loadAuthHelpers();

function context(overrides = {}) {
  return {
    id: "user-1",
    name: "User",
    email: null,
    role: "admin",
    department: null,
    location: null,
    is_active: true,
    tier: 1,
    xp: 0,
    streak: 0,
    last_login_at: null,
    auth_kind: "session",
    app_mode: "production",
    ...overrides,
  };
}

test("administration access fails closed for every non-admin context", () => {
  const cases = [
    undefined,
    null,
    context({ auth_kind: "demo_fallback" }),
    context({ app_mode: "demo" }),
    context({ role: "supervisor" }),
    context({ role: "agent" }),
    context({ is_active: false }),
    context({ role: null }),
  ];

  for (const candidate of cases) {
    assert.equal(canAccessAdministration(candidate), false);
  }
  assert.equal(canAccessAdministration(context()), true);
});

test("protected production sessions require a real active production session", () => {
  const cases = [
    undefined,
    null,
    context({ auth_kind: "demo_fallback" }),
    context({ app_mode: "demo" }),
    context({ is_active: false }),
  ];

  for (const candidate of cases) {
    assert.equal(hasProtectedProductionSession(candidate), false);
  }
  assert.equal(hasProtectedProductionSession(context({ role: "agent" })), true);
});

test("protected intelligence allows only production admin and supervisor sessions", () => {
  const denied = [
    undefined,
    null,
    context({ auth_kind: "demo_fallback" }),
    context({ app_mode: "demo" }),
    context({ role: "agent" }),
    context({ role: "unknown" }),
    context({ role: null }),
    context({ is_active: false }),
  ];

  for (const candidate of denied) {
    assert.equal(canAccessProtectedIntelligence(candidate), false);
  }
  assert.equal(canAccessProtectedIntelligence(context({ role: "admin" })), true);
  assert.equal(canAccessProtectedIntelligence(context({ role: "supervisor" })), true);
  assert.equal(canAccessProtectedIntelligence(context({ role: "SUPERVISOR" })), true);
});

test("demo administration state covers fallback and signed-in demo sessions", () => {
  assert.equal(isDemoContext(undefined), false);
  assert.equal(isDemoContext(context()), false);
  assert.equal(isDemoContext(context({ auth_kind: "demo_fallback" })), true);
  assert.equal(isDemoContext(context({ app_mode: "demo" })), true);

  assert.equal(isDemoAdministrationContext(undefined), false);
  assert.equal(isDemoAdministrationContext(context()), false);
  assert.equal(
    isDemoAdministrationContext(context({ auth_kind: "demo_fallback" })),
    true,
  );
  assert.equal(
    isDemoAdministrationContext(context({ app_mode: "demo" })),
    true,
  );
});
