const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("service request mutations are exposed only in the supported demo-admin context", () => {
  const source = read("app", "services", "page.tsx");

  assert.match(source, /const canManageCatalog = canManageOperationalRecords\(authQuery\.data\)/);
  assert.match(source, /const canOperateRequests = canManageCatalog && isDemoContext\(authQuery\.data\)/);
  assert.match(source, /<RequestResults requests=\{requests\} canManage=\{canOperateRequests\}/);
  assert.match(source, /\{canOperateRequests && <ConfirmDialog/);
  assert.match(source, /Production request state is owned by the connected ticketing system/);
});

test("asset and problem write surfaces fail closed while read views remain available", () => {
  const assets = read("app", "assets", "page.tsx");
  const problems = read("app", "problems", "page.tsx");

  for (const source of [assets, problems]) {
    assert.match(source, /const canManage = canManageOperationalRecords\(authQuery\.data\)/);
    assert.match(source, /getUsersPage\(\{ isActive: true, limit: 200 \}\)/);
    assert.match(source, /enabled: canManage/);
    assert.match(source, /Management access could not be verified/);
  }

  assert.match(assets, /<AssetResults assets=\{assets\} canManage=\{canManage\}/);
  assert.match(assets, /\{canManage && <AssetFormDialog/);
  assert.match(problems, /<ProblemDetailDialog problem=\{viewing\} canManage=\{canManage\}/);
  assert.match(problems, /\{canManage && <ProblemFormDialog/);
  assert.match(problems, /\{canManage && <IconButton[^>]+aria-label=\{`Unlink/);
});

test("operational editors preserve canonical lifecycle values and explicit clears", () => {
  const assets = read("app", "assets", "page.tsx");
  const problems = read("app", "problems", "page.tsx");

  assert.match(assets, /\["In Use", "Available", "Retired", "Broken", "Lost"\]/);
  assert.doesNotMatch(assets, /\["Active", "Inactive", "Retired", "In Repair", "Lost\/Stolen"\]/);
  assert.match(assets, /value\.trim\(\) \|\| \(asset \? null : undefined\)/);
  assert.match(assets, /title="Retire asset\?"/);
  assert.match(assets, /ticket and audit history remain intact/);

  assert.match(problems, /problem \? null : undefined/);
  assert.match(problems, /"Under Investigation"/);
  assert.match(problems, /Add investigation notes/);
  assert.match(problems, /Root cause/);
  assert.match(problems, /Closure evidence is incomplete/);
  assert.doesNotMatch(problems, /<option value="">Not set<\/option>/);
});
