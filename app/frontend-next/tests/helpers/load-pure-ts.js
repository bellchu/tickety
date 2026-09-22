const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Type-only imports are erased; runtime helpers must be explicitly supplied.
// Undeclared dependencies fail rather than loading application services implicitly.
function loadTs(source, dependencies) {
  const output = ts.transpileModule(fs.readFileSync(source, 'utf8'), {
    fileName: source,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const loaded = { exports: {} };
  new Function('exports', 'module', 'require', output)(loaded.exports, loaded, name => {
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
