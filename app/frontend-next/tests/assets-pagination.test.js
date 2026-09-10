const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

function loadApi() {
  const filename = path.join(root, "lib", "api.ts");
  const output = ts.transpileModule(read("lib", "api.ts"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  const compile = new Function("require", "exports", "module", output);
  compile((specifier) => {
    if (specifier === "@tanstack/react-query") return { QueryClient: class QueryClient {} };
    throw new Error(`Unexpected module: ${specifier}`);
  }, loaded.exports, loaded);
  return loaded.exports;
}

test("asset API encodes server filters and preserves response-header pagination", async () => {
  const { api } = loadApi();
  const originalFetch = global.fetch;
  const asset = { id: "asset-1", name: "Edge router" };
  global.fetch = async (url) => {
    assert.equal(
      url,
      "/api/assets?asset_type=Network+%26+Edge&status=Broken&search=TAG_100%25&limit=25&offset=50",
    );
    return new Response(JSON.stringify([asset]), {
      status: 200,
      headers: {
        "x-page-limit": "25",
        "x-page-offset": "50",
        "x-has-more": "true",
      },
    });
  };

  try {
    assert.deepEqual(await api.getAssetsPage({
      assetType: "Network & Edge",
      status: "Broken",
      search: " TAG_100% ",
      limit: 25,
      offset: 50,
    }), {
      assets: [asset],
      limit: 25,
      offset: 50,
      hasMore: true,
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test("asset inventory uses bounded infinite pages and preserves loaded rows on later failure", () => {
  const page = read("app", "assets", "page.tsx");
  const api = read("lib", "api.ts");
  const types = read("lib", "types.ts");

  assert.match(types, /export interface AssetPage/);
  assert.match(api, /getAssetsPage: async/);
  assert.doesNotMatch(api, /\bgetAssets:/);
  assert.match(page, /useInfiniteQuery/);
  assert.match(page, /api\.getAssetsPage/);
  assert.match(page, /assetType: assetType \|\| undefined/);
  assert.match(page, /status: status \|\| undefined/);
  assert.match(page, /search: debouncedSearch \|\| undefined/);
  assert.match(page, /limit: ASSET_PAGE_SIZE/);
  assert.match(page, /offset: pageParam/);
  assert.match(page, /data\?\.pages\.flatMap/);
  assert.match(page, /assetsQuery\.isError && !assets\.length/);
  assert.match(page, /assetsQuery\.isFetchNextPageError/);
  assert.match(page, /The assets already shown remain available/);
  assert.match(page, /assetsQuery\.fetchNextPage\(\)/);
  assert.match(page, />Load more assets<\/Button>/);
});
