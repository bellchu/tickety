"use client";

import { useEffect, useLayoutEffect, useState } from "react";
import { RecognitionToast } from "@/components/engagement/RecognitionToast";
import { SuccessBurst } from "@/components/engagement/SuccessBurst";
import { TierPromotionModal } from "@/components/engagement/TierPromotionModal";
import { useEngagementStore } from "@/lib/engagement-state";
import { createNotificationsWS } from "@/lib/ws";
import { rememberNotificationCursor } from "@/lib/notification-cursor";
import { isNotificationCursorAdvance, isPointsNotification } from "@/lib/realtime-validation";
import { canPresentEngagementModal, getStandardDialogCount, subscribeToStandardDialogs } from "@/lib/dialog-coordination";

export function AppExperience({
  children,
  realtimeEnabled,
  userId,
}: {
  children: React.ReactNode;
  realtimeEnabled: boolean;
  userId: string | null;
}) {
  const setNotification = useEngagementStore((state) => state.setNotification);
  const showPointsToast = useEngagementStore((state) => state.showPointsToast);
  const showRecognitionToast = useEngagementStore((state) => state.showRecognitionToast);
  const showTierPromotion = useEngagementStore((state) => state.showTierPromotion);
  const clearPointsToast = useEngagementStore((state) => state.clearPointsToast);
  const clearRecognitionToast = useEngagementStore((state) => state.clearRecognitionToast);
  const clearTierPromotion = useEngagementStore((state) => state.clearTierPromotion);
  const resetForUser = useEngagementStore((state) => state.resetForUser);
  const clearForUser = useEngagementStore((state) => state.clearForUser);
  // Do not expose an engagement dialog until the layout-phase registry knows
  // whether this route committed an ordinary Dialog in the same render.
  const [standardDialogCount, setStandardDialogCount] = useState<number | null>(null);

  useLayoutEffect(() => {
    const unsubscribe = subscribeToStandardDialogs(() => setStandardDialogCount(getStandardDialogCount()));
    // A route may mount with its work dialog already open before this effect
    // subscribes, so synchronize once after subscription as well, before paint.
    setStandardDialogCount(getStandardDialogCount());
    return unsubscribe;
  }, []);

  // Zustand is module-global, whereas auth sessions are not. Reset before
  // paint at the actual authenticated identity boundary and again on unmount
  // (logout/public navigation) so no award can bridge accounts.
  useLayoutEffect(() => {
    resetForUser(userId);
    return () => clearForUser(userId);
  }, [clearForUser, resetForUser, userId]);

  useEffect(() => {
    if (!realtimeEnabled || !userId) return;

    const ws = createNotificationsWS(userId);
    const unsubscribe = ws.onMessage((data) => {
      if (isPointsNotification(data) && data.user_id === userId) {
        rememberNotificationCursor(userId, data.event_id);
        setNotification(data);
      } else if (isNotificationCursorAdvance(data)) {
        // The backend emits this only for a replay row that failed its
        // business-payload contract. Advance recovery state without ever
        // rendering or trusting that rejected payload.
        rememberNotificationCursor(userId, data.cursor);
      }
    });
    // Install the handler before opening: a small replay page can arrive
    // immediately after the upgrade completes.
    ws.connect();

    return () => {
      unsubscribe();
      ws.disconnect();
    };
  }, [realtimeEnabled, setNotification, userId]);

  return (
    <>
      {children}
      {(showPointsToast || (showRecognitionToast && showRecognitionToast.recognitions_unlocked.length > 0)) && (
        <div className="fixed inset-x-4 bottom-4 z-50 flex flex-col gap-3 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:items-end">
          {showRecognitionToast && showRecognitionToast.recognitions_unlocked.length > 0 && (
            <RecognitionToast
              recognitions={showRecognitionToast.recognitions_unlocked}
              onClose={clearRecognitionToast}
            />
          )}
          {showPointsToast && (
            <SuccessBurst notification={showPointsToast} onClose={clearPointsToast} />
          )}
        </div>
      )}
      {showTierPromotion && canPresentEngagementModal(standardDialogCount) && (
        <TierPromotionModal
          notification={showTierPromotion}
          onClose={clearTierPromotion}
        />
      )}
    </>
  );
}
