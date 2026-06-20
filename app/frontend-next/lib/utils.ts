import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function priorityColor(priority: string): string {
  switch (priority) {
    case "P1": return "text-rust-500 bg-rust-400/10 border-rust-400/30";
    case "P2": return "text-amber-600 bg-amber-400/10 border-amber-400/30";
    case "P3": return "text-clay-500 bg-clay-400/10 border-clay-400/30";
    default: return "text-ink-500 bg-linen-300 border-linen-400";
  }
}

export function statusColor(status: string): string {
  switch (status) {
    case "New": return "text-ink-600 bg-linen-300 border-linen-400";
    case "Open": return "text-clay-500 bg-clay-400/10 border-clay-400/30";
    case "Processed": return "text-moss-600 bg-moss-500/10 border-moss-500/30";
    case "Closed": return "text-moss-600 bg-moss-500/15 border-moss-500/40";
    case "Escalated": return "text-amber-600 bg-amber-400/10 border-amber-400/30";
    case "Awaiting Review": return "text-clay-700 bg-clay-400/10 border-clay-400/30";
    default: return "text-ink-500 bg-linen-300 border-linen-400";
  }
}

export function sentimentColor(sentiment: string | null): string {
  if (!sentiment) return "text-ink-400";
  switch (sentiment) {
    case "Business-Critical": return "text-rust-600 bg-rust-400/10 border-rust-400/30";
    case "High-Impact": return "text-amber-600 bg-amber-400/10 border-amber-400/30";
    case "Moderate": return "text-clay-600 bg-clay-400/10 border-clay-400/30";
    case "Neutral": return "text-ink-500 bg-linen-300 border-linen-400";
    case "Positive": return "text-moss-600 bg-moss-500/10 border-moss-500/30";
    case "Very Negative": return "text-rust-600 bg-rust-400/10 border-rust-400/30";
    case "Negative": return "text-amber-600 bg-amber-400/10 border-amber-400/30";
    default: return "text-ink-400";
  }
}

export function moodEmoji(mood: string | null): string {
  if (!mood) return "😐";
  const map: Record<string, string> = {
    critical: "😡",
    urgent: "😤",
    concerned: "😟",
    neutral: "😐",
    satisfied: "🙂",
    // Legacy moods (older tickets):
    frustrated: "😤",
    anxious: "😟",
    angry: "😡",
  };
  return map[mood] || "😐";
}

// Urgency-driven badge styling for the mood tag, companion to sentimentColor.
export function moodUrgencyColor(mood: string | null): string {
  if (!mood) return "text-ink-500 bg-linen-300 border-linen-400";
  switch (mood) {
    case "critical": return "text-rust-600 bg-rust-400/10 border-rust-400/30";
    case "urgent": return "text-amber-600 bg-amber-400/10 border-amber-400/30";
    case "concerned": return "text-clay-600 bg-clay-400/10 border-clay-400/30";
    case "neutral": return "text-ink-500 bg-linen-300 border-linen-400";
    case "satisfied": return "text-moss-600 bg-moss-500/10 border-moss-500/30";
    case "angry": return "text-rust-600 bg-rust-400/10 border-rust-400/30";
    case "frustrated": return "text-amber-600 bg-amber-400/10 border-amber-400/30";
    case "anxious": return "text-clay-600 bg-clay-400/10 border-clay-400/30";
    default: return "text-ink-500 bg-linen-300 border-linen-400";
  }
}

export function moodLabel(mood: string | null): string {
  if (!mood) return "Unknown";
  return mood.charAt(0).toUpperCase() + mood.slice(1);
}

export function complexityDots(complexity: number): { filled: number; empty: number } {
  return { filled: Math.min(5, Math.max(1, complexity)), empty: 5 - Math.min(5, Math.max(1, complexity)) };
}

export function tierName(tier: number): string {
  return `Tier ${tier}`;
}

export function formatTimeAgo(dateStr: string | null): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function tierProgress(points: number): { current: number; needed: number; percent: number; tier: number } {
  const thresholds = [0, 100, 250, 500, 1000, 2000, 4000, 8000];
  let tier = 1;
  let needed = thresholds[1];
  for (let i = thresholds.length - 1; i >= 0; i--) {
    if (points >= thresholds[i]) {
      tier = i + 1;
      needed = thresholds[i + 1] || thresholds[i] * 2;
      break;
    }
  }
  const base = thresholds[tier - 1] || 0;
  const span = needed - base;
  const percent = span > 0 ? Math.min(100, ((points - base) / span) * 100) : 100;
  return { current: points - base, needed: span, percent, tier };
}