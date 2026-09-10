export const RECOGNITION_META: Record<string, { display_name: string; description: string; icon: string }> = {
  first_resolution: {
    display_name: "First Resolution",
    description: "Resolved your first ticket",
    icon: "medal",
  },
  consistent_performer: {
    display_name: "Consistent Performer",
    description: "Maintained 10-ticket processing momentum",
    icon: "flame",
  },
  critical_specialist: {
    display_name: "Critical Issue Specialist",
    description: "Resolved 5 P1 tickets",
    icon: "alert-octagon",
  },
  rapid_responder: {
    display_name: "Rapid Responder",
    description: "Resolved a ticket within 5 minutes",
    icon: "zap",
  },
  sentiment_expert: {
    display_name: "Sentiment Expert",
    description: "Correctly identified customer sentiment 10 times",
    icon: "heart",
  },
  reliability_streak: {
    display_name: "Reliability Streak",
    description: "Active contribution for 7 consecutive days",
    icon: "calendar-check",
  },
};

export const ALL_RECOGNITION_KEYS = Object.keys(RECOGNITION_META);

export const TIER_THRESHOLDS = [0, 100, 250, 500, 1000, 2000, 4000, 8000];