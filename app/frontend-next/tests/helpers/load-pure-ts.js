const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Type-only imports are erased; runtime helpers must be explicitly supplied.
// Keep application/API modules with runtime dependencies in their own harnesses.
function loadPureTs(filename, dependencies = {}) {
  const source = path.join(__dirname, '../../lib', filename);
  const output = ts.transpileModule(fs.readFileSync(source, 'utf8'), {
    fileName: source,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const loaded = { exports: {} };
  new Function('exports', 'module', 'require', output)(loaded.exports, loaded, name => {
    if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
    return dependencies[name];
  });
  return loaded.exports;
}

module.exports = { loadPureTs };
