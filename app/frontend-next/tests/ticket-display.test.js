const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadDisplayHelpers() {
  const filename = path.join(__dirname, "..", "lib", "ticket-display.ts");
  const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  new Function("require", "exports", "module", output)(require, loaded.exports, loaded);
  return loaded.exports;
}

test("requester display never presents a numeric provider id as a person's name", () => {
  const { requesterEmail, requesterName } = loadDisplayHelpers();
  const numeric = { reporter: "2001455211", requester_name: null, requester_email: null };
  const enriched = {
    reporter: "2001455211",
    requester_name: "Avery Chen",
    requester_email: "avery@example.com",
  };

  assert.equal(requesterName(numeric), "Requester profile pending");
  assert.equal(requesterEmail(numeric), null);
  assert.equal(requesterName(enriched), "Avery Chen");
  assert.equal(requesterEmail(enriched), "avery@example.com");
});

test("ticket timeline uses authoritative source creation and communication times", () => {
  const { ticketCreatedAt, ticketLastCommunicationAt } = loadDisplayHelpers();
  const ticket = {
    created_at: "2026-08-25T10:00:00Z",
    external_created_at: "2026-08-24T09:00:00Z",
    external_conversation_updated_at: "2026-08-24T11:00:00Z",
    last_communication_at: "2026-08-24T12:00:00Z",
  };

  assert.equal(ticketCreatedAt(ticket), "2026-08-24T09:00:00Z");
  assert.equal(ticketLastCommunicationAt(ticket), "2026-08-24T12:00:00Z");
});
