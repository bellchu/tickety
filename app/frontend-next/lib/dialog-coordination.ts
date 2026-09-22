/**
 * Tiny process-local registry for standard application dialogs. Engagement
 * promotions use it to wait until an operator has finished the task they are
 * already performing, rather than creating a second aria-modal dialog.
 */
let standardDialogCount = 0;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

export function getStandardDialogCount() {
  return standardDialogCount;
}

/** `null` means the layout-phase registry has not synchronized yet. */
export function canPresentEngagementModal(count: number | null) {
  return count === 0;
}

export function subscribeToStandardDialogs(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Register one mounted, open, non-engagement Dialog and return its cleanup. */
export function registerStandardDialog() {
  standardDialogCount += 1;
  notify();
  let released = false;
  return () => {
    if (released) return;
    released = true;
    standardDialogCount = Math.max(0, standardDialogCount - 1);
    notify();
  };
}
