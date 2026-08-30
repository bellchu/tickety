const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("primary product surfaces use the Tickety OPS Tower identity", () => {
  const brand = read("lib", "brand.ts");
  const logo = read("components", "layout", "TicketyLogo.tsx");
  const sidebar = read("components", "layout", "Sidebar.tsx");
  const layout = read("app", "layout.tsx");
  const manifest = read("app", "manifest.ts");
  const socialCard = read("public", "brand", "tickety-social-card.svg");

  assert.match(brand, /PRODUCT_NAME = "Tickety OPS Tower"/);
  assert.match(logo, /\{PRODUCT_NAME\}/);
  assert.match(logo, /aria-label=\{PRODUCT_LOCKUP_NAME\}/);
  assert.match(sidebar, /<TicketyLogo inverse layout="stacked" size="md" \/>/);
  assert.match(layout, /applicationName: PRODUCT_NAME/);
  assert.match(layout, /title: PRODUCT_MARKETING_TITLE/);
  assert.match(manifest, /short_name: PRODUCT_NAME/);
  assert.match(socialCard, /TICKETY OPS TOWER/);
});
