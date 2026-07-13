import type { AuthContext } from "./types";

export function canAccessAdministration(context?: AuthContext | null) {
  return Boolean(
    context?.auth_kind === "session" &&
    context.app_mode === "production" &&
    context.role.toLowerCase() === "admin"
  );
}

export function isDemoAdministrationContext(context?: AuthContext | null) {
  return Boolean(
    context &&
    (context.auth_kind === "demo_fallback" || context.app_mode === "demo")
  );
}
