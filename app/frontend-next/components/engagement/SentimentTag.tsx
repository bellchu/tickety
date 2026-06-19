import { cn, moodEmoji, moodLabel } from "@/lib/utils";

interface Props {
  mood: string | null;
  size?: "sm" | "md";
}

export function SentimentTag({ mood, size = "sm" }: Props) {
  if (!mood) return null;

  const emoji = moodEmoji(mood);
  const label = moodLabel(mood);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md font-medium",
        size === "sm" ? "text-xs px-2 py-0.5" : "text-sm px-2.5 py-1",
        mood === "angry" || mood === "frustrated"
          ? "bg-red-50 text-red-700"
          : mood === "anxious" || mood === "confused"
          ? "bg-slate-50 text-slate-600"
          : mood === "neutral"
          ? "bg-slate-50 text-slate-600"
          : "bg-slate-50 text-slate-600"
      )}
    >
      <span>{emoji}</span>
      <span>{label}</span>
    </span>
  );
}
