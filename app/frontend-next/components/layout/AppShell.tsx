"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { AppExperience } from "@/components/layout/AppExperience";
import { Footer } from "@/components/layout/Footer";
import { Sidebar } from "@/components/layout/Sidebar";
import { TicketyLogo } from "@/components/layout/TicketyLogo";

const PUBLIC_ROUTES = ["/login", "/portal"];

function isPublicRoute(pathname: string) {
  return PUBLIC_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`)
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setNavigationOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!navigationOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const navigation = document.getElementById("app-navigation");
    const focusable = navigation?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    focusable?.[0]?.focus();

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

  return (
    <AppExperience>
      <div className="min-h-screen bg-linen-100">
        <a
          href="#main-content"
          className="fixed left-4 top-3 z-[70] -translate-y-20 rounded-md bg-clay-500 px-3 py-2 text-sm font-semibold text-white shadow-lg transition-transform focus:translate-y-0 focus:outline-none focus:ring-2 focus:ring-white"
        >
          Skip to content
        </a>

        <Sidebar open={navigationOpen} onClose={() => setNavigationOpen(false)} />

        {navigationOpen && (
          <button
            type="button"
            aria-label="Close navigation"
            className="fixed inset-0 z-40 bg-[#07111d]/60 backdrop-blur-sm lg:hidden"
            onClick={() => {
              setNavigationOpen(false);
              menuButtonRef.current?.focus();
            }}
          />
        )}

        <div className="flex min-h-screen flex-col lg:pl-64">
          <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-linen-300 bg-linen-50/95 px-4 backdrop-blur-md lg:hidden">
            <TicketyLogo className="h-8" />
            <button
              ref={menuButtonRef}
              type="button"
              aria-label="Open navigation"
              aria-controls="app-navigation"
              aria-expanded={navigationOpen}
              onClick={() => setNavigationOpen(true)}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-linen-400 bg-white text-ink-600 shadow-sm transition-colors hover:bg-linen-200 focus:outline-none focus:ring-2 focus:ring-clay-400 focus:ring-offset-2"
            >
              <Menu className="h-5 w-5" aria-hidden="true" />
            </button>
          </header>

          <main id="main-content" tabIndex={-1} className="flex-1 outline-none">
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
