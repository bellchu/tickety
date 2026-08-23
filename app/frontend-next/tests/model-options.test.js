const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadModelOptionHelpers() {
  const filename = path.join(__dirname, "..", "lib", "model-options.ts");
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

const { filterModelOptions } = loadModelOptionHelpers();

const models = [
  { id: "foundry/DeepSeek-V4-Flash", label: "DeepSeek V4 Flash" },
  { id: "foundry/gpt-5.4", label: "GPT 5.4" },
  { id: "custom/deployment-east", label: "Support assistant" },
];

test("blank model searches preserve every available option", () => {
  assert.deepEqual(filterModelOptions(models, "   "), models);
});

test("model searches match labels case-insensitively", () => {
  assert.deepEqual(filterModelOptions(models, "deepseek"), [models[0]]);
  assert.deepEqual(filterModelOptions(models, "GPT 5.4"), [models[1]]);
});

test("model searches match provider and deployment IDs", () => {
  assert.deepEqual(filterModelOptions(models, "  DEPLOYMENT-EAST  "), [models[2]]);
  assert.deepEqual(filterModelOptions(models, "foundry/"), [models[0], models[1]]);
});

test("model searches return no options for an unknown model", () => {
  assert.deepEqual(filterModelOptions(models, "not-a-model"), []);
});
