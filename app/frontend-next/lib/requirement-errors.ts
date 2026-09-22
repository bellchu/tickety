const aiMessages: Record<string, string> = {
  ai_unavailable: "AI is unavailable. Check the configured provider in Settings. You can continue working manually.",
  invalid_ai_output: "The AI response could not be verified. Try again or continue working manually.",
  ai_rate_limit_exceeded: "AI request limit reached. Wait a minute before trying again; manual work is still available.",
  ai_daily_budget_exceeded: "Today's AI budget has been reached. You can continue working manually.",
};

const retryMessage = "The request could not be confirmed. Check your connection, then refresh to check the latest saved work before trying again.";

/** Translate interactive requirement failures without hiding actionable business validation. */
export function requirementErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) return retryMessage;
  const text = error.message.trim();
  if (Object.hasOwn(aiMessages, text)) return aiMessages[text];
  const status = "status" in error && typeof error.status === "number" ? error.status : undefined;
  if (status === 401) return "Your session has expired. Sign in again to continue.";
  if (status === 403) return "You do not have permission for this action. Ask the initiative owner or an administrator for help.";
  if (status === 429) return "Too many requests. Wait a minute before trying again.";
  if (status !== undefined && status >= 500) return "The service is temporarily unavailable. Refresh to check the latest saved work before trying again.";
  const generic = !text || /^API .+ failed: \d+$/.test(text) || /^\s*</.test(text);
  if (generic && status === 404) return "This initiative or record is no longer available. Return to the initiative list and reopen it.";
  if (generic && status === 409) return "The saved work has changed. Refresh and review the latest version before trying again.";
  if (generic && (status === 400 || status === 422)) return "Check the required fields, text lengths and selected records, then try again.";
  if (generic || /^(Failed to fetch|Load failed|NetworkError when attempting to fetch resource\.?|fetch failed)$/i.test(text)) return retryMessage;
  return text;
}
