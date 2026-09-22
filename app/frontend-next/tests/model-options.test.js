const { loadPureTs } = require("./helpers/load-pure-ts");
const assert = require("node:assert/strict");
const test = require("node:test");


const { filterModelOptions } = loadPureTs("model-options.ts");

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
