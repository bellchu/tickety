import { create } from "zustand";
import type { PointsNotification } from "./types";

/** Waiting award notifications, excluding the toast currently displayed. */
export const POINTS_TOAST_QUEUE_CAP = 3;
/** Important awards get a bounded reserve so a burst cannot erase promotion evidence. */
export const PRIORITY_POINTS_TOAST_QUEUE_CAP = 3;
/** Recognition cards wait independently of points-toast dismissal. */
export const RECOGNITION_TOAST_QUEUE_CAP = 3;
/** Durable outbox ids remembered for this browser session. */
export const SEEN_NOTIFICATION_EVENT_CAP = 100;

export interface EngagementNotificationState {
  /** Auth identity that owns every visible award and dedupe marker. */
  activeUserId: string | null;
  lastNotification: PointsNotification | null;
  showTierPromotion: PointsNotification | null;
  showPointsToast: PointsNotification | null;
  showRecognitionToast: PointsNotification | null;
  queuedPointsToasts: PointsNotification[];
  queuedPriorityPointsToasts: PointsNotification[];
  queuedRecognitionToasts: PointsNotification[];
  seenNotificationEventIds: number[];
  latestTotalByUser: Record<string, number>;
}

interface EngagementState extends EngagementNotificationState {
  setNotification: (n: PointsNotification) => void;
  resetForUser: (userId: string | null) => void;
  clearForUser: (userId: string | null) => void;
  clearPointsToast: () => void;
  clearRecognitionToast: () => void;
  clearTierPromotion: () => void;
}

function rememberEventId(seen: number[], eventId: number | undefined) {
  if (eventId === undefined) return seen;
  return [...seen, eventId].slice(-SEEN_NOTIFICATION_EVENT_CAP);
}

function isImportantAward(notification: PointsNotification) {
  return notification.tier_promoted || notification.recognitions_unlocked.length > 0;
}

/**
 * The reserve is bounded. If several important awards arrive during one
 * unusually large burst, retain their recognitions and highest tier together
 * instead of silently discarding the later result.
 */
function coalesceImportantAwards(existing: PointsNotification, incoming: PointsNotification): PointsNotification {
  const latest = incoming.new_total >= existing.new_total ? incoming : existing;
  const recognitions = new Map<string, PointsNotification["recognitions_unlocked"][number]>();
  for (const recognition of [...existing.recognitions_unlocked, ...incoming.recognitions_unlocked]) {
    recognitions.set(`${recognition.id}:${recognition.recognition_key}`, recognition);
  }
  return {
    ...latest,
    event_id: incoming.event_id,
    ticket_subject: "multiple resolved tickets",
    points_earned: existing.points_earned + incoming.points_earned,
    new_tier: Math.max(existing.new_tier, incoming.new_tier),
    tier_promoted: existing.tier_promoted || incoming.tier_promoted,
    recognitions_unlocked: [...recognitions.values()],
  };
}

function sameNotification(left: PointsNotification, right: PointsNotification) {
  if (left.event_id !== undefined && right.event_id !== undefined) return left.event_id === right.event_id;
  return left.user_id === right.user_id
    && left.ticket_id === right.ticket_id
    && left.new_total === right.new_total;
}

function queueRecognitionToast(queue: PointsNotification[], notification: PointsNotification) {
  if (queue.length < RECOGNITION_TOAST_QUEUE_CAP) return [...queue, notification];
  const lastIndex = queue.length - 1;
  return [
    ...queue.slice(0, lastIndex),
    coalesceImportantAwards(queue[lastIndex], notification),
  ];
}

function takeRecognitionForNotification(queue: PointsNotification[], notification: PointsNotification) {
  const index = queue.findIndex((candidate) => sameNotification(candidate, notification));
  if (index < 0) return { notification: null, queue };
  return {
    notification: queue[index],
    queue: [...queue.slice(0, index), ...queue.slice(index + 1)],
  };
}

/**
 * Applies an untrusted but schema-validated notification without allowing a
 * reconnect replay to regress visible totals or overwrite an active award.
 */
export function applyPointsNotification(
  state: EngagementNotificationState,
  notification: PointsNotification,
): EngagementNotificationState {
  if (state.activeUserId && notification.user_id !== state.activeUserId) return state;
  const eventId = notification.event_id;
  if (eventId !== undefined && state.seenNotificationEventIds.includes(eventId)) return state;

  const seenNotificationEventIds = rememberEventId(state.seenNotificationEventIds, eventId);
  const latestTotal = state.latestTotalByUser[notification.user_id];
  if (latestTotal !== undefined && notification.new_total <= latestTotal) {
    return { ...state, seenNotificationEventIds };
  }

  let queuedPointsToasts = state.queuedPointsToasts;
  let queuedPriorityPointsToasts = state.queuedPriorityPointsToasts;
  let queuedRecognitionToasts = state.queuedRecognitionToasts;
  if (state.showPointsToast) {
    if (queuedPointsToasts.length < POINTS_TOAST_QUEUE_CAP) {
      queuedPointsToasts = [...queuedPointsToasts, notification];
    } else if (isImportantAward(notification)) {
      if (queuedPriorityPointsToasts.length < PRIORITY_POINTS_TOAST_QUEUE_CAP) {
        queuedPriorityPointsToasts = [...queuedPriorityPointsToasts, notification];
      } else {
        const lastIndex = queuedPriorityPointsToasts.length - 1;
        queuedPriorityPointsToasts = [
          ...queuedPriorityPointsToasts.slice(0, lastIndex),
          coalesceImportantAwards(queuedPriorityPointsToasts[lastIndex], notification),
        ];
      }
    }
  }
  const displaysImmediately = !state.showPointsToast;
  const shouldShowRecognitionImmediately = displaysImmediately
    && !state.showRecognitionToast
    && notification.recognitions_unlocked.length > 0;
  if (notification.recognitions_unlocked.length > 0 && !shouldShowRecognitionImmediately) {
    queuedRecognitionToasts = queueRecognitionToast(queuedRecognitionToasts, notification);
  }

  return {
    ...state,
    lastNotification: notification,
    showPointsToast: state.showPointsToast ?? notification,
    showRecognitionToast: shouldShowRecognitionImmediately ? notification : state.showRecognitionToast,
    // Promotions are coupled to the current award toast, never a later queued event.
    showTierPromotion: state.showTierPromotion
      ?? (displaysImmediately && notification.tier_promoted ? notification : null),
    queuedPointsToasts,
    queuedPriorityPointsToasts,
    queuedRecognitionToasts,
    seenNotificationEventIds,
    latestTotalByUser: { ...state.latestTotalByUser, [notification.user_id]: notification.new_total },
  };
}

/**
 * Both waiting queues are FIFO internally. Select their earlier head so a
 * preserved promotion cannot jump ahead of older ordinary awards and make the
 * visible total regress. Durable ids are authoritative; legacy events for the
 * same user retain their increasing total order.
 */
function arrivesBefore(left: PointsNotification, right: PointsNotification) {
  if (left.event_id !== undefined && right.event_id !== undefined) {
    return left.event_id <= right.event_id;
  }
  if (left.user_id === right.user_id && left.new_total !== right.new_total) {
    return left.new_total < right.new_total;
  }
  // A reserve is only populated after the ordinary FIFO was full, so its
  // unknown-order legacy head follows the ordinary head by insertion order.
  return false;
}

/** Advances waiting notifications in the same non-regressing order they arrived. */
export function advancePointsToast(state: EngagementNotificationState): Pick<EngagementNotificationState, "showPointsToast" | "showRecognitionToast" | "showTierPromotion" | "queuedPointsToasts" | "queuedPriorityPointsToasts" | "queuedRecognitionToasts"> {
  const [priorityNext, ...queuedPriorityPointsToasts] = state.queuedPriorityPointsToasts;
  const [regularNext, ...remainingRegularToasts] = state.queuedPointsToasts;
  const usePriority = Boolean(priorityNext && (!regularNext || arrivesBefore(priorityNext, regularNext)));
  const next = usePriority ? priorityNext : regularNext;
  const pendingRecognition = !state.showRecognitionToast && next && next.recognitions_unlocked.length > 0
    ? takeRecognitionForNotification(state.queuedRecognitionToasts, next)
    : { notification: null, queue: state.queuedRecognitionToasts };
  return {
    showPointsToast: next ?? null,
    // A recognition is independently acknowledged. Advancing points must never
    // erase or replace the card the operator is still reading.
    showRecognitionToast: state.showRecognitionToast ?? pendingRecognition.notification,
    showTierPromotion: next?.tier_promoted ? next : null,
    queuedPointsToasts: usePriority ? state.queuedPointsToasts : remainingRegularToasts,
    queuedPriorityPointsToasts: usePriority ? queuedPriorityPointsToasts : state.queuedPriorityPointsToasts,
    queuedRecognitionToasts: pendingRecognition.queue,
  };
}

/** Recognition can be dismissed without affecting the paired points award. */
export function dismissRecognitionToast(): Pick<EngagementNotificationState, "showRecognitionToast"> {
  return { showRecognitionToast: null };
}

/** Reveal only the recognition that belongs to the currently visible award. */
export function advanceRecognitionToast(state: EngagementNotificationState): Pick<EngagementNotificationState, "showRecognitionToast" | "queuedRecognitionToasts"> {
  if (!state.showPointsToast) return { showRecognitionToast: null, queuedRecognitionToasts: state.queuedRecognitionToasts };
  const pendingRecognition = takeRecognitionForNotification(state.queuedRecognitionToasts, state.showPointsToast);
  return {
    showRecognitionToast: pendingRecognition.notification,
    queuedRecognitionToasts: pendingRecognition.queue,
  };
}

export function emptyEngagementState(userId: string | null): EngagementNotificationState {
  return {
    activeUserId: userId,
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

export const useEngagementStore = create<EngagementState>((set) => ({
  ...emptyEngagementState(null),
  // Defense in depth: even a future proxy/regression cannot surface a
  // payload whose user does not match the authenticated AppExperience owner.
  setNotification: (n) => set((state) => (
    state.activeUserId !== n.user_id ? state : applyPointsNotification(state, n)
  )),
  resetForUser: (userId) => set(emptyEngagementState(userId)),
  clearForUser: (userId) => set((state) => (
    state.activeUserId === userId ? emptyEngagementState(null) : state
  )),
  clearPointsToast: () => set((state) => advancePointsToast(state)),
  clearRecognitionToast: () => set((state) => advanceRecognitionToast(state)),
  clearTierPromotion: () => set({ showTierPromotion: null }),
}));
