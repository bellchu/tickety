import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { hasForbiddenClientMarkup } from "./static-notice-policy.js";

const markup = readFileSync(resolve(process.cwd(), "app/index.html"), "utf8");

test("disabled app is static and does not load the Freshworks client", () => {
  expect(markup).toContain("Embedded ticket intelligence is temporarily unavailable");
  expect(markup).toContain("No ticket data is requested or displayed");
  expect(hasForbiddenClientMarkup(markup)).toBe(false);
  expect(hasForbiddenClientMarkup("<script>window.app.initialized()</script>")).toBe(true);
  expect(markup).not.toMatch(/<script\b/i);
  expect(markup).not.toContain("{{{appclient}}}");
  expect(markup).not.toContain("scripts/app.js");
});
