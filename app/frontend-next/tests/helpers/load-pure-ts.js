const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const compiled = new Map();

// Type-only imports are erased; runtime helpers must be explicitly supplied.
// Undeclared dependencies fail rather than loading application services implicitly.
function loadTs(source, dependencies) {
  const content = fs.readFileSync(source, 'utf8');
  let entry = compiled.get(source);
  if (!entry || entry.content !== content) {
    const output = ts.transpileModule(content, {
      fileName: source,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText;
    entry = { content, execute: new Function('exports', 'module', 'require', output) };
    compiled.set(source, entry);
  }
  // Share compilation only: exports, module state and injected dependencies stay fresh.
  const loaded = { exports: {} };
  entry.execute(loaded.exports, loaded, name => {
    if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
    return dependencies[name];
  });
  return loaded.exports;
}

function loadPureTs(filename, dependencies = {}) {
  return loadTs(path.join(__dirname, '../../lib', filename), dependencies);
}

function loadComponentTs(filename, dependencies = {}) {
  return loadTs(path.join(__dirname, '../../components', filename), dependencies);
}

module.exports = { loadPureTs, loadComponentTs };
