"use client";

import { Star } from "lucide-react";
import type { PointsNotification } from "@/lib/types";
import { Button, Dialog } from "@/components/ui";

interface Props {
  notification: PointsNotification;
  onClose: () => void;
}

export function TierPromotionModal({ notification, onClose }: Props) {
  return (
    <Dialog
      open
      onOpenChange={(open) => { if (!open) onClose(); }}
      title={`Tier ${notification.new_tier} achieved`}
      description={`Congratulations, ${notification.user_name}. Your support impact has reached a new tier.`}
      footer={<Button onClick={onClose}>Continue</Button>}
    >
      <div className="py-3 text-center">
        <div className="mx-auto grid h-20 w-20 place-items-center rounded-2xl bg-[#010D1B] text-white shadow-lg" aria-hidden="true">
          <Star className="h-10 w-10 fill-current" />
        </div>
        <p className="mt-5 text-xs font-semibold uppercase tracking-[0.16em] text-semantic-primary">Tier promotion</p>
        <p className="mt-2 text-2xl font-semibold tracking-[-0.025em] text-ink-700">{notification.new_total} impact points</p>
        <p className="mt-2 text-sm leading-6 text-ink-500">This recognition remains visible until you choose to continue.</p>
      </div>
    </Dialog>
  );
}
