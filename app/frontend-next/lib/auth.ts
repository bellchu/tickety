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

/** True only for an active, authenticated administrator in either runtime mode. */
export function canUseAdministrativeFeatures(context?: AuthContext | null) {
  return Boolean(
    context?.auth_kind === "session" &&
    context.is_active === true &&
    normalizedRole(context) === "admin"
  );
}

export function hasDemoAdministratorSession(context?: AuthContext | null) {
  return Boolean(
    canUseAdministrativeFeatures(context) && context?.app_mode === "demo"
  );
}

export function canAccessAdministration(context?: AuthContext | null) {
  return canUseAdministrativeFeatures(context);
}

export function canAccessProtectedIntelligence(context?: AuthContext | null) {
  const role = normalizedRole(context);
  return Boolean(
    hasDemoAdministratorSession(context) ||
    (hasProtectedProductionSession(context) &&
      (role === "admin" || role === "supervisor"))
  );
}

export function canCreateTickets(context?: AuthContext | null) {
  return hasProtectedProductionSession(context) || hasDemoAdministratorSession(context);
}

export function isDemoContext(context?: AuthContext | null) {
  return Boolean(
    context &&
    (context.auth_kind === "demo_fallback" || context.app_mode === "demo")
  );
}

export function isDemoAdministrationContext(context?: AuthContext | null) {
  return Boolean(
    isDemoContext(context) && !hasDemoAdministratorSession(context)
  );
}
