const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("public survey page consumes and immediately scrubs fragment capabilities", () => {
  const page = read("app", "portal", "survey", "page.tsx");

  assert.match(page, /window\.location\.hash/);
  assert.match(page, /fragment\.get\("token"\)/);
  assert.match(page, /window\.history\.replaceState/);
  assert.match(page, /api\.lookupPortalSurvey\(capability\)/);
  assert.match(page, /api\.respondPortalSurvey\(token, rating, comment\.trim\(\)\)/);
  assert.match(page, /setLookup\(\{\s*status: "error",\s*alreadySubmitted: error\.status === 409/);
  assert.match(page, /disabled=\{!token \|\| rating === null\}/);
  assert.doesNotMatch(page, /localStorage|sessionStorage|console\.(?:log|error|warn)/);
  assert.doesNotMatch(page, /searchParams\.get\("token"\)/);
});

test("survey operations distinguish provider acceptance, failure, and retry state", () => {
  const page = read("app", "surveys", "page.tsx");

  assert.match(page, /Delivery accepted/);
  assert.match(page, /Provider-accepted deliveries/);
  assert.match(page, /Delivery failed/);
  assert.match(page, /Delivery unconfirmed/);
  assert.match(page, /delivery_status === "pending"/);
  assert.match(page, /delivery_status === "legacy"/);
  assert.match(page, /key=\{formOpen \? "open" : "closed"\}/);
  assert.match(page, /onRetryDependencies/);
  assert.match(page, /onSettled/);
  assert.match(page, /Load more deliveries/);
  assert.match(page, /surveysQuery\.isError && !surveys\.length/);
  assert.match(page, /surveysQuery\.isFetchNextPageError/);
  assert.match(page, /getSurveyEligibleTickets/);
  assert.match(page, /debouncedTicketSearch/);
  assert.match(page, /ticketHasMore/);
  assert.match(page, /Find a resolved ticket/);
  assert.doesNotMatch(page, /getTicketsPage\(\{ limit: 200/);
  assert.doesNotMatch(page, /All delivery attempts/);
});

test("legacy arbitrary-ID survey response client contract is removed", () => {
  const api = read("lib", "api.ts");

  assert.doesNotMatch(api, /respondSurvey:\s*\(surveyId/);
  assert.match(api, /"\/portal\/survey\/lookup"/);
  assert.match(api, /"\/portal\/survey\/respond"/);
  assert.match(api, /\/surveys\/eligible-tickets/);
});
