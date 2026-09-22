const assert = require("node:assert/strict");
const test = require("node:test");
const { loadPureTs } = require("./helpers/load-pure-ts");

test("standard-dialog registry releases exactly once and tells engagement UI when it may present", () => {
  const {
    getStandardDialogCount,
    canPresentEngagementModal,
    registerStandardDialog,
    subscribeToStandardDialogs,
  } = loadPureTs("dialog-coordination.ts");
  const observed = [];
  assert.equal(canPresentEngagementModal(null), false, "engagement modal waits for layout-phase dialog synchronization");
  assert.equal(canPresentEngagementModal(1), false, "an open FollowUpDialog or another work dialog blocks it");
  assert.equal(canPresentEngagementModal(0), true, "it is released before paint when no standard dialog is open");
  const unsubscribe = subscribeToStandardDialogs(() => observed.push(getStandardDialogCount()));
  const releaseFirst = registerStandardDialog();
  const releaseSecond = registerStandardDialog();

  assert.equal(getStandardDialogCount(), 2);
  releaseFirst();
  releaseFirst();
  assert.equal(getStandardDialogCount(), 1, "Strict Mode cleanup or repeated teardown cannot underflow the registry");
  releaseSecond();
  assert.equal(getStandardDialogCount(), 0, "a deferred tier promotion can render after the work dialog closes");
  assert.deepEqual(observed, [1, 2, 1, 0]);
  unsubscribe();
});
