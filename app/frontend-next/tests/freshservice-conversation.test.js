const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const ts = require("typescript");

const componentPath = path.join(
  __dirname,
  "..",
  "components",
  "ticket",
  "FreshserviceConversationThread.tsx",
);

function loadConversationModule() {
  const source = fs.readFileSync(componentPath, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: componentPath,
  }).outputText;
  const loaded = { exports: {} };
  const icon = (props) => React.createElement("span", props);
  const compile = new Function("require", "exports", "module", output);

  compile((specifier) => {
    if (specifier === "react/jsx-runtime") return require("react/jsx-runtime");
    if (specifier === "@tanstack/react-query") return { useInfiniteQuery() { throw new Error("query wrapper was rendered unexpectedly"); } };
    if (specifier === "lucide-react") return { LockKeyhole: icon, MessageSquareText: icon };
    if (specifier === "@/lib/api") return { api: {} };
    if (specifier === "@/lib/utils") return { formatTimeAgo: () => "recently" };
    if (specifier === "@/components/ui") {
      return {
        Alert: ({ title, children }) => React.createElement("div", null, title, children),
        Button: ({ children }) => React.createElement("button", null, children),
        Skeleton: () => React.createElement("div", { "data-skeleton": true }),
      };
    }
    throw new Error(`Unexpected module: ${specifier}`);
  }, loaded.exports, loaded);

  return { ...loaded.exports, source };
}

function ticket(overrides = {}) {
  return {
    id: "ticket-1",
    description: "The printer is showing error 50.",
    reporter: "Avery Requester",
    created_at: "2026-08-24T10:00:00Z",
    external_created_at: "2026-08-24T09:59:00Z",
    ...overrides,
  };
}

function comment(overrides = {}) {
  return {
    id: 1,
    ticket_id: "ticket-1",
    author_id: null,
    author_name: "Freshservice user 7",
    body: "Please restart the printer.",
    is_private: false,
    created_at: "2026-08-24T10:05:00Z",
    ...overrides,
  };
}

test("Freshservice conversation renders the request and replies as an ordered BBS thread", () => {
  const { FreshserviceConversationThreadView } = loadConversationModule();
  const html = renderToStaticMarkup(React.createElement(FreshserviceConversationThreadView, {
    ticket: ticket(),
    comments: [
      comment(),
      comment({ id: 2, author_name: "Agent Rivera", body: "Internal diagnostic", is_private: true }),
    ],
    loading: false,
    error: false,
    hasOlderReplies: false,
    loadingOlderReplies: false,
    onLoadOlderReplies() {},
    onRetry() {},
  }));

  assert.ok(html.indexOf("The printer is showing error 50.") < html.indexOf("Please restart the printer."));
  assert.ok(html.indexOf("Please restart the printer.") < html.indexOf("Internal diagnostic"));
  assert.match(html, /Freshservice thread/);
  assert.match(html, /Original post/);
  assert.match(html, /#1/);
  assert.match(html, /#2/);
  assert.match(html, /#3/);
  assert.match(html, /Private note/);
  assert.match(html, /Read only/);
  assert.match(html, /3 posts shown/);
  assert.doesNotMatch(html, /textarea|contenteditable/i);
});

test("comment pages merge from the oldest API page to the latest", () => {
  const { mergeChronologicalCommentPages } = loadConversationModule();
  const latestPage = [comment({ id: 3 }), comment({ id: 4 })];
  const olderPage = [comment({ id: 1 }), comment({ id: 2 })];

  assert.deepEqual(
    mergeChronologicalCommentPages([latestPage, olderPage]).map(({ id }) => id),
    [1, 2, 3, 4],
  );
});

test("Freshservice detail composes the read-only thread before source metadata", () => {
  const pageSource = fs.readFileSync(
    path.join(__dirname, "..", "app", "tickets", "[id]", "page.tsx"),
    "utf8",
  );
  const branch = pageSource.slice(
    pageSource.indexOf('ticket.external_source === "freshservice"'),
    pageSource.indexOf(") : (", pageSource.indexOf('ticket.external_source === "freshservice"')),
  );

  assert.ok(branch.indexOf("<FreshserviceConversationThread") >= 0);
  assert.ok(branch.indexOf("<FreshserviceConversationThread") < branch.indexOf("<FreshserviceSourcePanel"));
  assert.doesNotMatch(branch, /AgentActionPanel ticket=\{ticket\}/);
});

test("Freshservice conversation component contains no write path", () => {
  const { source } = loadConversationModule();

  assert.doesNotMatch(source, /api\.addComment|useMutation|<textarea|<form/);
  assert.match(source, /api\.getComments/);
});
