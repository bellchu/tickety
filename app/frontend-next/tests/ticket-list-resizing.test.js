const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.join(__dirname, "..", "components", "ticket", "TicketList.tsx"),
  "utf8",
);

test("desktop ticket columns expose persistent pointer and keyboard resizing", () => {
  assert.match(source, /function ResizableColumnHeader/);
  assert.match(source, /onPointerDown=/);
  assert.match(source, /event\.key !== "ArrowLeft"/);
  assert.match(source, /COLUMN_WIDTHS_KEY/);
  assert.match(source, /localStorage\.setItem\(COLUMN_WIDTHS_KEY/);
  assert.match(source, /<col style=\{\{ width: columnWidths\.routing \}\} \/>/);
  assert.match(source, /priority: 150/);
  assert.match(source, /label="Priority signal"/);
});

test("routing content remains discoverable when space is constrained", () => {
  assert.match(source, /<ListText text=\{routingLabel\(ticket\)\} lines=\{2\}/);
  assert.match(source, /<ListText text=\{routingLabel\(ticket\)\} lines="wrap"/);
});
