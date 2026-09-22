const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { loadPureTs } = require('./helpers/load-pure-ts');

test('compiled helpers retain fresh state and dependencies and notice source edits', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tickety-loader-'));
  const file = path.join(directory, 'fixture.ts');
  const filename = path.relative(path.join(__dirname, '../lib'), file);
  try {
    fs.writeFileSync(file, 'import { value } from "injected"; export const state: number[] = []; export const result = value + 1;');
    const first = loadPureTs(filename, { injected: { value: 1 } });
    first.state.push(9);
    const second = loadPureTs(filename, { injected: { value: 5 } });
    assert.deepEqual(second.state, []);
    assert.equal(second.result, 6);
    assert.equal(first.result, 2);
    assert.throws(() => loadPureTs(filename), /Unexpected dependency: injected/);
    fs.writeFileSync(file, 'export const result = 42;');
    assert.equal(loadPureTs(filename).result, 42);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});
