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
});

test("routing content remains discoverable when space is constrained", () => {
  assert.match(source, /title=\{routingLabel\(ticket\)\}/);
  assert.match(source, /<dd className="mt-1 break-words font-semibold text-ink-600">\{routingLabel\(ticket\)\}<\/dd>/);
});
