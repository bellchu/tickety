"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/api";
import { useEffect } from "react";
import { createNotificationsWS } from "@/lib/ws";
import { useEngagementStore } from "@/lib/engagement-state";
import { SuccessBurst } from "@/components/engagement/SuccessBurst";
import { RecognitionToast } from "@/components/engagement/RecognitionToast";
import { TierPromotionModal } from "@/components/engagement/TierPromotionModal";

export function Providers({ children }: { children: React.ReactNode }) {
  const setNotification = useEngagementStore((s) => s.setNotification);
  const showPointsToast = useEngagementStore((s) => s.showPointsToast);
  const showTierPromotion = useEngagementStore((s) => s.showTierPromotion);
  const clearPointsToast = useEngagementStore((s) => s.clearPointsToast);
  const clearTierPromotion = useEngagementStore((s) => s.clearTierPromotion);

  useEffect(() => {
    const ws = createNotificationsWS();
    ws.connect();
    const unsub = ws.onMessage((data) => {
      if (data.ticket_id && data.points_earned !== undefined) {
        setNotification(data);
      }
    });
    return () => {
      unsub();
      ws.disconnect();
    };
  }, [setNotification]);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {showPointsToast && (
        <SuccessBurst
          notification={showPointsToast}
          onClose={clearPointsToast}
        />
      )}
      {showPointsToast &&
        showPointsToast.recognitions_unlocked.length > 0 && (
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
    </QueryClientProvider>
  );
}
