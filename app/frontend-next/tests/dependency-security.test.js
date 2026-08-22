const assert = require("node:assert/strict");
const test = require("node:test");

const packageJson = require("../package.json");
const packageLock = require("../package-lock.json");

const NANOID_SECURITY_FLOOR = [3, 3, 18];

function versionAtLeast(version, floor) {
  const parts = version.split(".").map((part) => Number.parseInt(part, 10));
  for (let index = 0; index < floor.length; index += 1) {
    if (parts[index] !== floor[index]) return parts[index] > floor[index];
  }
  return true;
}

test("nanoid resolution keeps the audited production security floor", () => {
  assert.equal(packageJson.overrides.nanoid, "^3.3.18");

  const resolved = packageLock.packages["node_modules/nanoid"]?.version;
  assert.ok(resolved, "package-lock.json must resolve nanoid");
  assert.ok(
    versionAtLeast(resolved, NANOID_SECURITY_FLOOR),
    `nanoid ${resolved} is below the audited 3.3.18 security floor`
  );
});
