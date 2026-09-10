const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("incremental page failures preserve already loaded operational records", () => {
  for (const [relativePath, query, rows, message] of [
    [["app", "changes", "page.tsx"], "changesQuery", "filtered", "change records already shown"],
    [["app", "problems", "page.tsx"], "problemsQuery", "filtered", "problem records already shown"],
    [["app", "surveys", "page.tsx"], "surveysQuery", "surveys", "delivery records already shown"],
    [["app", "knowledge", "page.tsx"], "articlesQuery", "visibleArticles", "articles already shown"],
  ]) {
    const source = read(...relativePath);
    assert.match(source, new RegExp(`${query}\\.isError && !${rows}\\.length`));
    assert.match(source, new RegExp(`${query}\\.isFetchNextPageError`));
    assert.match(source, new RegExp(message, "i"));
    assert.match(source, new RegExp(`${query}\\.fetchNextPage\\(\\)`));
  }
});
