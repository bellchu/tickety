const assert = require("node:assert/strict");
const test = require("node:test");

const nextConfig = require("../next.config.js");

test("production build IDs are deterministic lowercase URL path segments", async () => {
  const previous = process.env.NEXT_PUBLIC_BUILD_SHA;
  process.env.NEXT_PUBLIC_BUILD_SHA = "5969CF83+dirty/36BEE4B6A728";
  try {
    assert.equal(
      await nextConfig.generateBuildId(),
      "5969cf83-dirty-36bee4b6a728",
    );
  } finally {
    if (previous === undefined) delete process.env.NEXT_PUBLIC_BUILD_SHA;
    else process.env.NEXT_PUBLIC_BUILD_SHA = previous;
  }
});
