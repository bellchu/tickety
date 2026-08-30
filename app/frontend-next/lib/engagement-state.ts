import { create } from "zustand";
import type { PointsNotification } from "./types";

interface EngagementState {
  lastNotification: PointsNotification | null;
  showTierPromotion: PointsNotification | null;
  showPointsToast: PointsNotification | null;
  setNotification: (n: PointsNotification) => void;
  clearPointsToast: () => void;
  clearTierPromotion: () => void;
}

export const useEngagementStore = create<EngagementState>((set) => ({
  lastNotification: null,
  showTierPromotion: null,
  showPointsToast: null,
  setNotification: (n) =>
    set({
      lastNotification: n,
      showPointsToast: n,
      showTierPromotion: n.tier_promoted ? n : null,
    }),
  clearPointsToast: () => set({ showPointsToast: null }),
  clearTierPromotion: () => set({ showTierPromotion: null }),
}));