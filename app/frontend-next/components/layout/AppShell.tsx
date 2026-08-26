"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "lucide-react";
import { AppExperience } from "@/components/layout/AppExperience";
import { Footer } from "@/components/layout/Footer";
import { LoginLink } from "@/components/layout/LoginLink";
import { Sidebar } from "@/components/layout/Sidebar";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { api, APIError, queryClient } from "@/lib/api";
import { getCurrentNavigationItem } from "@/lib/navigation";
import type { AuthContext } from "@/lib/types";

const PUBLIC_ROUTES = ["/login", "/portal"];

function isPublicRoute(pathname: string) {
  return PUBLIC_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`)
  );
}

function crossesAuthorizationBoundary(previous: AuthContext, next: AuthContext) {
  const previousRole = typeof previous.role === "string" ? previous.role.toLowerCase() : "";
  const nextRole = typeof next.role === "string" ? next.role.toLowerCase() : "";
  return previous.id !== next.id
    || previousRole !== nextRole
    || previous.is_active !== next.is_active
    || previous.auth_kind !== next.auth_kind
    || previous.app_mode !== next.app_mode;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [authState, setAuthState] = useState<"checking" | "authenticated" | "error">("checking");
  const [authContext, setAuthContext] = useState<AuthContext | null>(null);
  const [authAttempt, setAuthAttempt] = useState(0);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const currentNavigationItem = getCurrentNavigationItem(pathname);

  useEffect(() => {
    setNavigationOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (isPublicRoute(pathname)) {
      // Login is a user-isolation boundary. No data from the previous session
      // may survive into the next SPA navigation.
      queryClient.clear();
      setAuthContext(null);
      setAuthState("authenticated");
      return;
    }

    let cancelled = false;
    setAuthState("checking");
    api.getAuthMe()
      .then((context) => {
        if (!cancelled) {
          const previous = queryClient.getQueryData<AuthContext>(["auth-me"]);
          if (previous && crossesAuthorizationBoundary(previous, context)) {
            queryClient.clear();
          }
          queryClient.setQueryData(["auth-me"], context);
          setAuthContext(context);
          setAuthState("authenticated");
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // Never let a previously privileged identity survive a failed access
        // check in the shared query cache.
        queryClient.clear();
        setAuthContext(null);
        if (error instanceof APIError && error.status === 401) {
          const destination = `${window.location.pathname}${window.location.search}`;
          router.replace(`/login?next=${encodeURIComponent(destination)}`);
          return;
        }
        setAuthState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authAttempt, pathname, router]);

  useEffect(() => {
    if (!navigationOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const navigation = document.getElementById("app-navigation");
    const focusable = navigation?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    const closeButton = navigation?.querySelector<HTMLElement>(
      'button[aria-label="Close navigation"]'
    );
    (closeButton || focusable?.[0])?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setNavigationOpen(false);
        menuButtonRef.current?.focus();
        return;
      }

      if (event.key !== "Tab" || !focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [navigationOpen]);

  if (isPublicRoute(pathname)) return <>{children}</>;

  if (authState === "checking") {
    return (
      <main className="nexora-ambient grid min-h-screen place-items-center" aria-busy="true">
        <div className="flex flex-col items-center gap-4 text-sm text-ink-500">
          <TicketyLogo size="lg" />
          <span>Checking your session…</span>
        </div>
      </main>
    );
  }

  if (authState === "error") {
    return (
      <main className="nexora-ambient grid min-h-screen place-items-center p-6">
        <div role="alert" className="w-full max-w-md rounded-2xl border border-linen-400 bg-white p-7 text-center shadow-[var(--shadow-raised)]">
          <TicketyLogo size="lg" />
          <h1 className="mt-5 text-lg font-semibold text-ink-700">Workspace connection unavailable</h1>
          <p className="mt-2 text-sm leading-6 text-ink-500">
            Tickety could not verify this session, so protected workspace data remains hidden. Check your connection and retry.
          </p>
          <button
            type="button"
            onClick={() => setAuthAttempt((attempt) => attempt + 1)}
            className="relative mt-5 inline-flex min-h-10 items-center justify-center rounded-md border border-transparent bg-ink-700 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-ink-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2"
          >
            Retry session check
          </button>
        </div>
      </main>
    );
  }

  return (
    <AppExperience realtimeEnabled={authContext?.auth_kind === "session"}>
      <div className="nexora-ambient min-h-screen">
        <a
          href="#main-content"
          className="fixed left-4 top-3 z-[70] -translate-y-20 rounded-md bg-ink-700 px-3 py-2 text-sm font-semibold text-white shadow-lg transition-transform focus:translate-y-0 focus:outline-none focus:ring-2 focus:ring-white"
        >
          Skip to content
        </a>

        <Sidebar open={navigationOpen} onClose={() => setNavigationOpen(false)} />

        {navigationOpen && (
          <button
            type="button"
            aria-label="Close navigation"
            className="fixed inset-0 z-40 bg-[#010D1B]/70 backdrop-blur-sm lg:hidden"
            onClick={() => {
              setNavigationOpen(false);
              menuButtonRef.current?.focus();
            }}
          />
        )}

        <div className="flex min-h-screen w-full min-w-0 flex-col lg:pl-[17rem]">
          <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-linen-300 bg-linen-50/95 px-4 shadow-[0_1px_0_rgba(1,13,27,0.02)] backdrop-blur-md lg:hidden">
            <Link
              href="/"
              className="min-w-0 rounded-md focus:outline-none focus:ring-2 focus:ring-clay-400"
            >
              <TicketyLogo size="sm" />
              <span className="mt-1 block max-w-[8.5rem] whitespace-normal break-words text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-400 [overflow-wrap:anywhere]">
                {currentNavigationItem?.label || "Workspace"}
              </span>
            </Link>
            <div className="flex items-center gap-2">
              {authContext?.auth_kind === "demo_fallback" && (
                <LoginLink className="border-linen-400 bg-white text-ink-700 shadow-sm hover:bg-linen-200" />
              )}
              <button
                ref={menuButtonRef}
                type="button"
                aria-label="Open navigation"
                aria-controls="app-navigation"
                aria-expanded={navigationOpen}
                onClick={() => setNavigationOpen(true)}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-linen-400 bg-white px-3 text-ink-600 shadow-sm transition-colors hover:bg-linen-200 focus:outline-none focus:ring-2 focus:ring-clay-400 focus:ring-offset-2"
              >
                <Menu className="h-5 w-5" aria-hidden="true" />
                <span className="text-sm font-semibold">Menu</span>
              </button>
            </div>
          </header>

          <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 outline-none">
            <div className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
              {children}
            </div>
          </main>
          <Footer />
        </div>
      </div>
    </AppExperience>
  );
}
