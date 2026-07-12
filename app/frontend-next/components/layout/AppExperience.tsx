"use client";

import { useEffect } from "react";
import { RecognitionToast } from "@/components/engagement/RecognitionToast";
import { SuccessBurst } from "@/components/engagement/SuccessBurst";
import { TierPromotionModal } from "@/components/engagement/TierPromotionModal";
import { useEngagementStore } from "@/lib/engagement-state";
import { createNotificationsWS } from "@/lib/ws";

export function AppExperience({ children }: { children: React.ReactNode }) {
  const setNotification = useEngagementStore((state) => state.setNotification);
  const showPointsToast = useEngagementStore((state) => state.showPointsToast);
  const showTierPromotion = useEngagementStore((state) => state.showTierPromotion);
  const clearPointsToast = useEngagementStore((state) => state.clearPointsToast);
  const clearTierPromotion = useEngagementStore((state) => state.clearTierPromotion);

  useEffect(() => {
    const ws = createNotificationsWS();
    ws.connect();
    const unsubscribe = ws.onMessage((data) => {
      if (data.ticket_id && data.points_earned !== undefined) {
        setNotification(data);
      }
    });

    return () => {
      unsubscribe();
      ws.disconnect();
    };
  }, [setNotification]);

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
