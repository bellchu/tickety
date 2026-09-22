const { loadPureTs } = require("./helpers/load-pure-ts");
const assert = require("node:assert/strict");
const test = require("node:test");

const {
  applyPointsNotification,
  advancePointsToast,
  advanceRecognitionToast,
  dismissRecognitionToast,
  POINTS_TOAST_QUEUE_CAP,
  PRIORITY_POINTS_TOAST_QUEUE_CAP,
  RECOGNITION_TOAST_QUEUE_CAP,
  SEEN_NOTIFICATION_EVENT_CAP,
  emptyEngagementState,
} = loadPureTs("engagement-state.ts", {
  zustand: { create: initializer => initializer(() => {}) },
});

function notification(eventId, total, overrides = {}) {
  return {
    ...(eventId === undefined ? {} : { event_id: eventId }),
    ticket_id: `ticket-${total}`,
    ticket_subject: `Ticket ${total}`,
    user_id: "agent-1",
    user_name: "Agent",
    points_earned: 10,
    new_total: total,
    new_tier: 1,
    tier_promoted: false,
    new_momentum: 1,
    recognitions_unlocked: [],
    ...overrides,
  };
}

function emptyState() {
  return {
    lastNotification: null,
    showTierPromotion: null,
    showPointsToast: null,
    showRecognitionToast: null,
    queuedPointsToasts: [],
    queuedPriorityPointsToasts: [],
    queuedRecognitionToasts: [],
    seenNotificationEventIds: [],
    latestTotalByUser: {},
  };
}

test("engagement notifications deduplicate durable ids and reject non-advancing totals per user", () => {
  const first = notification(101, 10);
  const accepted = applyPointsNotification(emptyState(), first);
  assert.equal(accepted.showPointsToast, first);
  assert.deepEqual(accepted.seenNotificationEventIds, [101]);

  assert.equal(applyPointsNotification(accepted, first), accepted, "a reconnect replay is ignored");

  const delayed = applyPointsNotification(accepted, notification(102, 9));
  assert.equal(delayed.lastNotification, first);
  assert.equal(delayed.showPointsToast, first);
  assert.deepEqual(delayed.seenNotificationEventIds, [101, 102], "discarded durable events remain idempotent");

  const legacyReplay = applyPointsNotification(delayed, notification(undefined, 10));
  assert.equal(legacyReplay.lastNotification, first, "legacy events remain protected by totals");

  const otherUser = applyPointsNotification(delayed, notification(103, 1, { user_id: "agent-2" }));
  assert.equal(otherUser.lastNotification.user_id, "agent-2", "totals are scoped to the notification user");
});

test("engagement state is reset at the authenticated identity boundary", () => {
  const a = notification(41, 10, { user_id: "agent-a" });
  const b = notification(42, 10, { user_id: "agent-b" });
  const aState = applyPointsNotification(emptyEngagementState("agent-a"), a);
  assert.equal(aState.showPointsToast?.user_id, "agent-a");
  assert.equal(applyPointsNotification(aState, b), aState, "foreign socket data is ignored");

  const bState = emptyEngagementState("agent-b");
  assert.equal(bState.showPointsToast, null, "A's visible toasts never cross into B");
  assert.deepEqual(bState.seenNotificationEventIds, [], "A's idempotency cursor does not suppress B");
  const deliveredToB = applyPointsNotification(bState, b);
  assert.equal(deliveredToB.showPointsToast, b, "B still receives new awards after the reset");
});

test("engagement awards use a bounded FIFO and gate promotions to the matching toast", () => {
  const tierAward = notification(1, 10, { tier_promoted: true, new_tier: 2 });
  let state = applyPointsNotification(emptyState(), tierAward);
  const awards = Array.from({ length: POINTS_TOAST_QUEUE_CAP + 1 }, (_, index) => notification(index + 2, 20 + index * 10));
  for (const award of awards) state = applyPointsNotification(state, award);

  assert.equal(state.showTierPromotion, tierAward, "later non-tier awards keep the promotion open");
  assert.deepEqual(state.queuedPointsToasts.map(item => item.event_id), awards.slice(0, POINTS_TOAST_QUEUE_CAP).map(item => item.event_id));
  assert.equal(state.queuedPointsToasts.length, POINTS_TOAST_QUEUE_CAP);

  const advanced = { ...state, ...advancePointsToast(state) };
  assert.equal(advanced.showPointsToast?.event_id, awards[0].event_id, "dismissal reveals the oldest waiting award");
  assert.equal(advanced.queuedPointsToasts.length, POINTS_TOAST_QUEUE_CAP - 1);

  let ordered = applyPointsNotification(emptyState(), tierAward);
  const middleAward = notification(20, 20);
  const laterPromotion = notification(21, 30, { tier_promoted: true, new_tier: 3 });
  ordered = applyPointsNotification(ordered, middleAward);
  ordered = applyPointsNotification(ordered, laterPromotion);
  ordered = { ...ordered, showTierPromotion: null };
  assert.equal(ordered.showTierPromotion, null, "acknowledging A does not promote queued C early");
  ordered = { ...ordered, ...advancePointsToast(ordered) };
  assert.equal(ordered.showPointsToast, middleAward);
  assert.equal(ordered.showTierPromotion, null, "non-tier B keeps C's modal gated");
  ordered = { ...ordered, ...advancePointsToast(ordered) };
  assert.equal(ordered.showPointsToast, laterPromotion);
  assert.equal(ordered.showTierPromotion, laterPromotion, "C opens only when C becomes current");

  const recognitionAward = notification(30, 40, { recognitions_unlocked: [{ id: 1 }] });
  const recognitionState = applyPointsNotification(emptyState(), recognitionAward);
  assert.equal(dismissRecognitionToast().showRecognitionToast, null);
  assert.equal(recognitionState.showPointsToast, recognitionAward, "recognition dismissal leaves the points award usable");

  const seen = Array.from({ length: SEEN_NOTIFICATION_EVENT_CAP - 1 }, (_, index) => index + 1);
  const bounded = applyPointsNotification({ ...emptyState(), seenNotificationEventIds: seen }, notification(SEEN_NOTIFICATION_EVENT_CAP, 1));
  assert.equal(bounded.seenNotificationEventIds.length, SEEN_NOTIFICATION_EVENT_CAP);
  assert.equal(bounded.seenNotificationEventIds[0], 1);
});

test("important awards survive a full normal queue and bounded overflow preserves their result", () => {
  let state = applyPointsNotification(emptyState(), notification(1, 10));
  for (let index = 0; index < POINTS_TOAST_QUEUE_CAP; index += 1) {
    state = applyPointsNotification(state, notification(index + 2, 20 + index * 10));
  }

  const promoted = notification(20, 50, {
    tier_promoted: true,
    new_tier: 2,
    recognitions_unlocked: [{ id: 20, recognition_key: "first" }],
  });
  state = applyPointsNotification(state, promoted);
  assert.deepEqual(state.queuedPriorityPointsToasts, [promoted]);

  const visibleTotals = [state.showPointsToast.new_total];
  state = { ...state, ...advancePointsToast(state) };
  visibleTotals.push(state.showPointsToast.new_total);
  const laterNormal = notification(21, 60);
  state = applyPointsNotification(state, laterNormal);
  for (let index = 0; index < 4; index += 1) {
    state = { ...state, ...advancePointsToast(state) };
    visibleTotals.push(state.showPointsToast.new_total);
    if (state.showPointsToast === promoted) {
      assert.equal(state.showTierPromotion, promoted);
      assert.equal(state.showRecognitionToast, promoted);
    }
  }
  assert.deepEqual(visibleTotals, [10, 20, 30, 40, 50, 60], "important reserve entries never make visible totals move backwards");

  // The reserve remains bounded even under a pathological burst. Its final
  // entry is a displayable aggregate rather than a silently discarded award.
  let overflowState = applyPointsNotification(emptyState(), notification(100, 10));
  for (let index = 0; index < POINTS_TOAST_QUEUE_CAP; index += 1) {
    overflowState = applyPointsNotification(overflowState, notification(101 + index, 20 + index * 10));
  }
  for (let index = 0; index < PRIORITY_POINTS_TOAST_QUEUE_CAP + 1; index += 1) {
    overflowState = applyPointsNotification(overflowState, notification(110 + index, 60 + index * 10, {
      tier_promoted: true,
      new_tier: 3 + index,
      recognitions_unlocked: [{ id: 30 + index, recognition_key: `recognition-${index}` }],
    }));
  }
  assert.equal(overflowState.queuedPriorityPointsToasts.length, PRIORITY_POINTS_TOAST_QUEUE_CAP);
  const aggregate = overflowState.queuedPriorityPointsToasts.at(-1);
  assert.equal(aggregate.new_tier, 6);
  assert.deepEqual(aggregate.recognitions_unlocked.map(item => item.recognition_key), ["recognition-2", "recognition-3"]);
});

test("closing points never clears the active recognition, and the next recognition waits for its award", () => {
  const firstRecognition = notification(1, 10, { recognitions_unlocked: [{ id: 1, recognition_key: "first" }] });
  const laterWithoutRecognition = notification(2, 20);
  let state = applyPointsNotification(emptyState(), firstRecognition);
  state = applyPointsNotification(state, laterWithoutRecognition);
  state = { ...state, ...advancePointsToast(state) };
  assert.equal(state.showPointsToast, laterWithoutRecognition);
  assert.equal(state.showRecognitionToast, firstRecognition, "A remains visible after A points is dismissed and B has none");
  state = { ...state, ...advanceRecognitionToast(state) };
  assert.equal(state.showRecognitionToast, null, "A is removed only after explicit recognition dismissal");

  const laterRecognition = notification(3, 30, { recognitions_unlocked: [{ id: 3, recognition_key: "later" }] });
  state = applyPointsNotification(emptyState(), firstRecognition);
  state = applyPointsNotification(state, laterRecognition);
  state = { ...state, ...advancePointsToast(state) };
  assert.equal(state.showPointsToast, laterRecognition);
  assert.equal(state.showRecognitionToast, firstRecognition, "B cannot overwrite A while A is still acknowledged");
  state = { ...state, ...advanceRecognitionToast(state) };
  assert.equal(state.showRecognitionToast, laterRecognition, "explicitly closing A reveals B once B is the current award");
});

test("pending recognitions remain bounded while preserving a displayable overflow aggregate", () => {
  let state = applyPointsNotification(emptyState(), notification(100, 10, { recognitions_unlocked: [{ id: 100, recognition_key: "current" }] }));
  for (let index = 0; index < RECOGNITION_TOAST_QUEUE_CAP + 1; index += 1) {
    state = applyPointsNotification(state, notification(101 + index, 20 + index * 10, {
      recognitions_unlocked: [{ id: 101 + index, recognition_key: `pending-${index}` }],
    }));
  }
  assert.equal(state.queuedRecognitionToasts.length, RECOGNITION_TOAST_QUEUE_CAP);
  const aggregate = state.queuedRecognitionToasts.at(-1);
  assert.deepEqual(aggregate.recognitions_unlocked.map(item => item.recognition_key), ["pending-2", "pending-3"]);
});
