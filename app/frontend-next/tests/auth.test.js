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
  canCreateTickets,
  canAccessProtectedIntelligence,
  canUseAdministrativeFeatures,
  hasDemoAdministratorSession,
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

test("administration access permits real active administrators in demo and production", () => {
  const cases = [
    undefined,
    null,
    context({ auth_kind: "demo_fallback" }),
    context({ app_mode: "demo", auth_kind: "demo_fallback" }),
    context({ role: "supervisor" }),
    context({ role: "agent" }),
    context({ is_active: false }),
    context({ role: null }),
  ];

  for (const candidate of cases) {
    assert.equal(canAccessAdministration(candidate), false);
  }
  assert.equal(canAccessAdministration(context()), true);
  assert.equal(canAccessAdministration(context({ app_mode: "demo" })), true);
});

test("demo administrator capability requires a real active admin session", () => {
  const denied = [
    undefined,
    context({ auth_kind: "demo_fallback", app_mode: "demo" }),
    context({ app_mode: "demo", role: "supervisor" }),
    context({ app_mode: "demo", role: "agent" }),
    context({ app_mode: "demo", is_active: false }),
  ];
  for (const candidate of denied) {
    assert.equal(canUseAdministrativeFeatures(candidate), false);
    assert.equal(hasDemoAdministratorSession(candidate), false);
  }
  assert.equal(canUseAdministrativeFeatures(context()), true);
  assert.equal(hasDemoAdministratorSession(context()), false);
  assert.equal(hasDemoAdministratorSession(context({ app_mode: "demo" })), true);
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

test("protected intelligence allows production admins and supervisors plus demo admins", () => {
  const denied = [
    undefined,
    null,
    context({ auth_kind: "demo_fallback" }),
    context({ auth_kind: "demo_fallback", app_mode: "demo" }),
    context({ app_mode: "demo", role: "supervisor" }),
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
  assert.equal(canAccessProtectedIntelligence(context({ app_mode: "demo" })), true);
});

test("ticket creation permits authenticated production users and demo admins only", () => {
  assert.equal(canCreateTickets(context({ role: "agent" })), true);
  assert.equal(canCreateTickets(context({ app_mode: "demo" })), true);
  assert.equal(canCreateTickets(context({ auth_kind: "demo_fallback", app_mode: "demo" })), false);
  assert.equal(canCreateTickets(context({ app_mode: "demo", role: "supervisor" })), false);
  assert.equal(canCreateTickets(context({ app_mode: "demo", is_active: false })), false);
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
  assert.equal(isDemoAdministrationContext(context({ app_mode: "demo" })), false);
  assert.equal(isDemoAdministrationContext(context({ app_mode: "demo", role: "supervisor" })), true);
});
