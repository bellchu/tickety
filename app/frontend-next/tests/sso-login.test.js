const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadHelpers() {
  const filename = path.join(__dirname, "..", "lib", "sso-login.ts");
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

const { hasActiveSession, safeNextPath, ssoErrorMessage, ssoLoginUrl } = loadHelpers();

test("SSO preserves only same-origin application destinations", () => {
  assert.equal(safeNextPath("?next=%2Ftickets%2F123%3Ftab%3Dactivity"), "/tickets/123?tab=activity");
  assert.equal(safeNextPath("?next=https%3A%2F%2Fevil.example"), "/");
  assert.equal(safeNextPath("?next=%2F%2Fevil.example"), "/");
  assert.equal(safeNextPath("?next=%2Flogin%3Fnext%3D%252Flogin"), "/");
  assert.equal(safeNextPath("?next=%2Fapi%2Fauth%2Fsso%2Fcallback"), "/");
});

test("SSO login URL carries the intended destination", () => {
  assert.equal(
    ssoLoginUrl("/settings?section=access"),
    "/api/auth/sso/login?next=%2Fsettings%3Fsection%3Daccess",
  );
});

test("SSO errors are stable and user-facing", () => {
  assert.match(ssoErrorMessage("?sso_error=account_not_provisioned"), /not been granted/);
  assert.match(ssoErrorMessage("?sso_error=group_not_allowed"), /not a member/);
  assert.match(ssoErrorMessage("?sso_error=group_claim_overage"), /could not be verified/);
  assert.match(ssoErrorMessage("?sso_error=unknown"), /could not be completed/);
  assert.equal(ssoErrorMessage(""), "");
});

test("an active session takes precedence over a stale SSO error", () => {
  assert.equal(hasActiveSession({ auth_kind: "session", is_active: true }), true);
  assert.equal(hasActiveSession({ auth_kind: "session", is_active: false }), false);
  assert.equal(hasActiveSession({ auth_kind: "demo_fallback", is_active: true }), false);
  assert.equal(hasActiveSession(null), false);
});
