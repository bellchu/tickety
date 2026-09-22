const { loadPureTs } = require("./helpers/load-pure-ts");
const assert = require("node:assert/strict");
const test = require("node:test");


function loadUtils() {
  return loadPureTs("utils.ts", {
    "./date-time": loadPureTs("date-time.ts"),
    clsx: require("clsx"),
    "tailwind-merge": require("tailwind-merge"),
  });
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
