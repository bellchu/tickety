const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const changesPage = fs.readFileSync(path.join(__dirname, "..", "app", "changes", "page.tsx"), "utf8");
const types = fs.readFileSync(path.join(__dirname, "..", "lib", "types.ts"), "utf8");

test("change details load every approval through bounded infinite pages", () => {
  assert.match(changesPage, /const CHANGE_APPROVAL_PAGE_SIZE = 50/);
  assert.match(changesPage, /queryKey: \["change-approvals", change\?\.id\]/);
  assert.match(changesPage, /initialPageParam: 0/);
  assert.match(changesPage, /api\.getChangeApprovals\(change!\.id, \{ limit: CHANGE_APPROVAL_PAGE_SIZE, offset: pageParam \}\)/);
  assert.match(changesPage, /lastPage\.offset \+ lastPage\.approvals\.length/);
  assert.match(changesPage, /pages\.flatMap\(\(page\) => page\.approvals\)/);
  assert.match(changesPage, /Load more approvals/);
});

test("later approval page failures keep loaded decisions visible and retryable", () => {
  assert.match(changesPage, /approvalsQuery\.isError && !approvals\.length/);
  assert.match(changesPage, /approvalsQuery\.isFetchNextPageError/);
  assert.match(changesPage, /More approvals could not be loaded/);
  assert.match(changesPage, /The approvals already shown remain available/);
  assert.match(changesPage, /approvalsQuery\.fetchNextPage\(\)/);
});

test("anonymized approvals stay visible but can never trigger a decision", () => {
  assert.match(types, /approver_id: string \| null/);
  assert.match(changesPage, /approval\.approver_name \|\| approval\.approver_id \|\| "Deleted account"/);
  assert.match(changesPage, /!user\?\.is_active \|\| !approval\.approver_id/);
  assert.match(changesPage, /if \(decision\?\.approval\.approver_id && current && canDecideChangeApproval/);
});
