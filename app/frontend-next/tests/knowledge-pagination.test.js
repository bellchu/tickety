const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("knowledge library uses server-scoped status filters and bounded pagination", () => {
  const page = read("app", "knowledge", "page.tsx");
  const api = read("lib", "api.ts");

  assert.match(page, /useInfiniteQuery/);
  assert.match(page, /serverStatus/);
  assert.match(page, /status: serverStatus/);
  assert.match(page, /limit: 20/);
  assert.match(page, /Load 20 more/);
  assert.match(page, /articlesQuery\.isError && !visibleArticles\.length/);
  assert.match(page, /articlesQuery\.isFetchNextPageError/);
  assert.match(page, /The articles already shown remain available/);
  assert.match(page, /api\.getKbArticle\(id\)/);
  assert.match(page, /canManage/);
  assert.match(page, /api\.getKbCategories\(canManage\)/);
  assert.match(page, /canManage \? "all" : "published"/);
  assert.match(page, /articleExcerpt/);
  assert.match(page, /-webkit-line-clamp:3/);
  assert.doesNotMatch(api, /params\.set\("limit", "500"\)/);
  assert.match(api, /status\?: "all" \| "published" \| "draft" \| "archived"/);
  assert.match(api, /x-page-offset/);
});
