const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// For dependency-free library modules (type-only imports are erased).
// Keep application/API modules with runtime dependencies in their own harnesses.
function loadPureTs(filename) {
  const source = path.join(__dirname, '../../lib', filename);
  const output = ts.transpileModule(fs.readFileSync(source, 'utf8'), {
    fileName: source,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const loaded = { exports: {} };
  new Function('exports', 'module', output)(loaded.exports, loaded);
  return loaded.exports;
}

module.exports = { loadPureTs };
