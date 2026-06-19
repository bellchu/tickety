import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function priorityColor(priority: string): string {
  switch (priority) {
    case "P1": return "text-red-600 bg-red-50 border-red-200";
    case "P2": return "text-amber-600 bg-amber-50 border-amber-200";
    case "P3": return "text-blue-600 bg-blue-50 border-blue-200";
    default: return "text-gray-600 bg-gray-50 border-gray-200";
  }
}

export function statusColor(status: string): string {
  switch (status) {
    case "New": return "text-slate-600 bg-slate-50 border-slate-200";
    case "Open": return "text-blue-600 bg-blue-50 border-blue-200";
    case "Processed": return "text-emerald-600 bg-emerald-50 border-emerald-200";
    case "Closed": return "text-emerald-700 bg-emerald-100 border-emerald-300";
    case "Escalated": return "text-orange-600 bg-orange-50 border-orange-200";
    case "Awaiting Review": return "text-purple-600 bg-purple-50 border-purple-200";
    default: return "text-gray-600 bg-gray-50 border-gray-200";
  }
}

export function sentimentColor(sentiment: string | null): string {
  if (!sentiment) return "text-gray-400";
  switch (sentiment) {
    case "Business-Critical": return "text-red-700 bg-red-50 border-red-200";
    case "High-Impact": return "text-orange-700 bg-orange-50 border-orange-200";
    case "Moderate": return "text-amber-700 bg-amber-50 border-amber-200";
    case "Neutral": return "text-slate-600 bg-slate-50 border-slate-200";
    case "Positive": return "text-emerald-700 bg-emerald-50 border-emerald-200";
    // Legacy values (older tickets) still render sensibly:
    case "Very Negative": return "text-red-700 bg-red-50 border-red-200";
    case "Negative": return "text-orange-700 bg-orange-50 border-orange-200";
    default: return "text-gray-400";
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
  if (!mood) return "text-slate-600 bg-slate-50 border-slate-200";
  switch (mood) {
    case "critical": return "text-red-700 bg-red-50 border-red-200";
    case "urgent": return "text-orange-700 bg-orange-50 border-orange-200";
    case "concerned": return "text-amber-700 bg-amber-50 border-amber-200";
    case "neutral": return "text-slate-600 bg-slate-50 border-slate-200";
    case "satisfied": return "text-emerald-700 bg-emerald-50 border-emerald-200";
    // Legacy moods:
    case "angry": return "text-red-700 bg-red-50 border-red-200";
    case "frustrated": return "text-orange-700 bg-orange-50 border-orange-200";
    case "anxious": return "text-amber-700 bg-amber-50 border-amber-200";
    default: return "text-slate-600 bg-slate-50 border-slate-200";
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