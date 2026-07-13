import type { AuthContext } from "./types";

function normalizedRole(context?: AuthContext | null) {
  return typeof context?.role === "string" ? context.role.toLowerCase() : "";
}

export function hasProtectedProductionSession(context?: AuthContext | null) {
  return Boolean(
    context?.auth_kind === "session" &&
    context.app_mode === "production" &&
    context.is_active === true
  );
}

export function canAccessAdministration(context?: AuthContext | null) {
  return Boolean(
    hasProtectedProductionSession(context) &&
    normalizedRole(context) === "admin"
  );
}

export function canAccessProtectedIntelligence(context?: AuthContext | null) {
  const role = normalizedRole(context);
  return Boolean(
    hasProtectedProductionSession(context) &&
    (role === "admin" || role === "supervisor")
  );
}

export function isDemoContext(context?: AuthContext | null) {
  return Boolean(
    context &&
    (context.auth_kind === "demo_fallback" || context.app_mode === "demo")
  );
}

export function isDemoAdministrationContext(context?: AuthContext | null) {
  return isDemoContext(context);
}
