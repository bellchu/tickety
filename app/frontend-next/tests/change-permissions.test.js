const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const changesPage = fs.readFileSync(path.join(__dirname, "..", "app", "changes", "page.tsx"), "utf8");

test("change register loads the current identity before exposing management actions", () => {
  assert.match(changesPage, /queryKey: \["auth-me"\], queryFn: api\.getAuthMe, retry: false/);
  assert.match(changesPage, /const verifiedCurrentUser = authQuery\.isError \? undefined : authQuery\.data/);
  assert.match(changesPage, /canManageChangeRecords\(verifiedCurrentUser\)/);
  assert.match(changesPage, /\["admin", "supervisor"\]\.includes\(user\.role\.toLowerCase\(\)\)/);
  assert.match(changesPage, /queryKey: \["users", "change-options"\][^\n]+getUsersPage\(\{ isActive: true, limit: 200 \}\)[^\n]+enabled: canManageChanges/);
  assert.match(changesPage, /actions=\{canManageChanges \?/);
  assert.match(changesPage, /canEdit=\{canManageChanges && !TERMINAL_STATUSES\.has\(change\.status\)\}/);
  assert.match(changesPage, /canDelete=\{canManageChanges && change\.status === "Draft"\}/);
  assert.match(changesPage, /\{canManageChanges && <ChangeFormDialog/);
  assert.match(changesPage, /\{canManageChanges && <ConfirmDialog open=\{Boolean\(deleting\)\}/);
  assert.match(changesPage, /remains available in read-only mode until your access can be verified/);
});

test("approval decisions are shown only to the assigned approver or an admin", () => {
  assert.match(changesPage, /const assigned = approval\.approver_id === user\.id/);
  assert.match(changesPage, /const admin = user\.role\.toLowerCase\(\) === "admin"/);
  assert.match(changesPage, /const requester = change\.requested_by === user\.id/);
  assert.match(changesPage, /return \(assigned \|\| admin\) && !requester/);
  assert.match(changesPage, /APPROVAL_OPEN_STATUSES\.has\(change\.status\)/);
  assert.match(changesPage, /canDecide=\{canDecideChangeApproval\(currentUser, current, approval\)\}/);
  assert.match(changesPage, /!decided && canDecide &&/);
  assert.match(changesPage, /onConfirm=\{\(\) => \{ if \(decision\?\.approval\.approver_id && current && canDecideChangeApproval\(currentUser, current, decision\.approval\)\)/);
});

test("change controls expose only canonical forward lifecycle actions", () => {
  assert.match(changesPage, /const TERMINAL_STATUSES = new Set\(\["Completed", "Rejected", "Cancelled"\]\)/);
  assert.match(changesPage, /const CREATE_STATUSES = \["Draft", "Submitted"\]/);
  assert.match(changesPage, /Draft: \["Submitted", "Cancelled"\]/);
  assert.match(changesPage, /"In Progress": \["Completed", "Cancelled"\]/);
  assert.match(changesPage, /\? \[change\.status, \.\.\.\(CHANGE_TRANSITIONS\[change\.status\] \?\? \[\]\)\]/);
  assert.match(changesPage, /change\?\.priority \?\? "P2"/);
  assert.doesNotMatch(changesPage, /<option value="">Not set<\/option>/);
  assert.match(changesPage, /Drafts with approval or ticket history are retained for audit/);
  assert.match(changesPage, /isEligibleOperationalUser/);
});

test("approver assignment remains a manager-only write action", () => {
  assert.match(changesPage, /\{canManage && APPROVAL_OPEN_STATUSES\.has\(current\.status\) && <div className="flex gap-2">/);
  assert.match(changesPage, /canManage && usersUnavailable &&/);
  assert.match(changesPage, /canManage && addMutation\.error &&/);
  assert.match(changesPage, /description=\{canManage \? "Add the first reviewer/);
});

test("change register pages and searches on the server without hiding CAB review", () => {
  assert.match(changesPage, /useInfiniteQuery\(\{/);
  assert.match(changesPage, /api\.getChangesPage\(\{ status: statusFilter \|\| undefined, search: debouncedSearch \|\| undefined, limit: 25, offset: pageParam \}\)/);
  assert.match(changesPage, /setDebouncedSearch\(search\.trim\(\)\), 300/);
  assert.match(changesPage, /"CAB Review"/);
  assert.match(changesPage, /Load more changes/);
  assert.match(changesPage, /APPROVAL_OPEN_STATUSES\.has\(current\.status\)/);
});
