export interface SsoLoginConfig {
  enabled: boolean;
  ready: boolean;
  provider: string;
  provider_type: "entra" | "okta" | "oidc";
  redirect_uri: string;
}

const SSO_ERROR_MESSAGES: Record<string, string> = {
  access_denied: "Sign-in was cancelled before access was granted.",
  account_deactivated: "Your Tickety account is deactivated. Contact an administrator.",
  account_not_provisioned: "Your organization account is valid, but it has not been granted Tickety access yet.",
  configuration_changed: "Single sign-on settings changed during sign-in. Please start again.",
  configuration_error: "Single sign-on is not fully configured. Contact an administrator.",
  domain_not_allowed: "This organization account is not in an allowed email domain.",
  group_not_allowed: "Your organization account is valid, but it is not a member of a group allowed to use Tickety.",
  group_claim_overage: "Your group membership could not be verified from the sign-in token. Contact an administrator.",
  expired_request: "That sign-in request expired. Please start again.",
  identity_conflict: "This organization identity cannot be linked automatically. Contact an administrator.",
  invalid_identity: "The identity provider response could not be verified. Please try again or contact an administrator.",
  invalid_state: "That sign-in request is no longer valid. Please start again.",
  provider_error: "The identity provider could not complete sign-in. Please try again.",
  provider_unavailable: "Single sign-on is temporarily unavailable. Please try again shortly.",
};

export function safeNextPath(search: string): string {
  const candidate = new URLSearchParams(search).get("next")?.trim() || "/";
  if (!candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return "/";
  }
  try {
    const parsed = new URL(candidate, "https://tickety.invalid");
    if (parsed.origin !== "https://tickety.invalid") return "/";
    if (parsed.pathname.startsWith("/login") || parsed.pathname.startsWith("/api/auth/")) return "/";
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return "/";
  }
}

export function ssoErrorMessage(search: string): string {
  const code = new URLSearchParams(search).get("sso_error") || "";
  return code ? SSO_ERROR_MESSAGES[code] || "Single sign-on could not be completed. Please try again." : "";
}

export function hasActiveSession(context: unknown): boolean {
  if (!context || typeof context !== "object") return false;
  const candidate = context as { auth_kind?: unknown; is_active?: unknown };
  return candidate.auth_kind === "session" && candidate.is_active === true;
}

export function ssoLoginUrl(nextPath: string): string {
  const params = new URLSearchParams({ next: nextPath });
  return `/api/auth/sso/login?${params.toString()}`;
}
