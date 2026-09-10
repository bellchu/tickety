"use client";

import { useEffect } from "react";
import { RecognitionToast } from "@/components/engagement/RecognitionToast";
import { SuccessBurst } from "@/components/engagement/SuccessBurst";
import { TierPromotionModal } from "@/components/engagement/TierPromotionModal";
import { useEngagementStore } from "@/lib/engagement-state";
import { createNotificationsWS } from "@/lib/ws";
import { isPointsNotification } from "@/lib/realtime-validation";

export function AppExperience({
  children,
  realtimeEnabled,
}: {
  children: React.ReactNode;
  realtimeEnabled: boolean;
}) {
  const setNotification = useEngagementStore((state) => state.setNotification);
  const showPointsToast = useEngagementStore((state) => state.showPointsToast);
  const showTierPromotion = useEngagementStore((state) => state.showTierPromotion);
  const clearPointsToast = useEngagementStore((state) => state.clearPointsToast);
  const clearTierPromotion = useEngagementStore((state) => state.clearTierPromotion);

  useEffect(() => {
    if (!realtimeEnabled) return;

    const ws = createNotificationsWS();
    ws.connect();
    const unsubscribe = ws.onMessage((data) => {
      if (isPointsNotification(data)) {
        setNotification(data);
      }
    });

    return () => {
      unsubscribe();
      ws.disconnect();
    };
  }, [realtimeEnabled, setNotification]);

  return (
    <>
      {children}
      {showPointsToast && (
        <SuccessBurst notification={showPointsToast} onClose={clearPointsToast} />
      )}
      {showPointsToast && showPointsToast.recognitions_unlocked.length > 0 && (
        <RecognitionToast
          recognitions={showPointsToast.recognitions_unlocked}
          onClose={clearPointsToast}
        />
      )}
      {showTierPromotion && (
        <TierPromotionModal
          notification={showTierPromotion}
          onClose={clearTierPromotion}
        />
      )}
    </>
  );
}
