"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { canAccessAdministration, canAccessProtectedIntelligence, isDemoContext } from "@/lib/auth";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { SyncIndicator } from "@/components/layout/SyncIndicator";
import { LoginLink } from "@/components/layout/LoginLink";
import { LogoutButton } from "@/components/layout/LogoutButton";
import { ProductIcon } from "@/components/icons/ProductIcon";
import {
  isNavigationItemActive,
  navigationSections,
  type NavigationIconKey,
  type NavigationVisibility,
} from "@/lib/navigation";
import {
  LayoutDashboard,
  Inbox,
  Users,
  BookOpen,
  BarChart3,
  TrendingUp,
  Settings as SettingsIcon,
  Radar,
  Package,
  AlertOctagon,
  GitBranch,
  Laptop,
  MessageSquareHeart,
  Clock3,
  ChevronRight,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navigationIcons: Record<NavigationIconKey, typeof LayoutDashboard> = {
  dashboard: LayoutDashboard,
  tickets: Inbox,
  time: Clock3,
  services: Package,
  problems: AlertOctagon,
  changes: GitBranch,
  assets: Laptop,
  knowledge: BookOpen,
  agents: Users,
  surveys: MessageSquareHeart,
  leaderboard: TrendingUp,
  reports: BarChart3,
  intelligence: Radar,
};

function initials(name?: string) {
  if (!name) return "ME";
  return name
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function Sidebar({
  open = false,
  onClose,
}: {
  open?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const { data: me } = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canAccessAdmin = canAccessAdministration(me);
  const canAccessIntelligence = canAccessProtectedIntelligence(me);
  const isDemoWorkspace = isDemoContext(me);
  const isDemoFallback = me?.auth_kind === "demo_fallback";
  const showLogin = isDemoFallback;
  const showLogout = me?.auth_kind === "session";
  const canSeeItem = (visibility: NavigationVisibility) => (
    visibility === "all"
    || (visibility === "admin" && canAccessAdmin)
    || (visibility === "intelligence" && canAccessIntelligence)
  );

  return (
    <aside
      id="app-navigation"
      aria-label="Application navigation"
      aria-modal={open ? "true" : undefined}
      role={open ? "dialog" : undefined}
      className={cn(
        "fixed inset-y-0 left-0 z-50 flex w-[17rem] flex-col border-r border-white/10 bg-[#010D1B] text-white shadow-2xl transition-transform duration-200 ease-out lg:translate-x-0 lg:shadow-none",
        open ? "translate-x-0" : "-translate-x-full"
      )}
    >
      <div className="flex h-20 items-center justify-between border-b border-white/10 px-5">
        <Link href="/" className="-ml-0.5 rounded-md focus:outline-none focus:ring-2 focus:ring-clay-400" onClick={onClose}>
          <TicketyLogo inverse showDescriptor size="md" />
        </Link>
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-clay-400 lg:hidden"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <nav aria-label="Workspace" className="flex-1 space-y-5 overflow-y-auto px-3 py-5">
        {navigationSections.map((group) => {
          const visibleItems = group.items.filter((item) => canSeeItem(item.visibility));
          if (!visibleItems.length) return null;
          const groupId = `nav-${group.label.toLowerCase().replaceAll(" ", "-")}`;
          const groupActive = visibleItems.some((item) => isNavigationItemActive(pathname, item.href));
          return (
            <div key={group.label} role="group" aria-labelledby={groupId}>
              <div
                id={groupId}
                className={cn(
                  "px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.15em] transition-colors",
                  groupActive ? "text-slate-300" : "text-slate-500"
                )}
              >
                {group.label}
              </div>
              <div className="space-y-1">
                {visibleItems.map((item) => {
                  const Icon = navigationIcons[item.icon];
                  const active = isNavigationItemActive(pathname, item.href);
                  return (
                    <Link
                      key={item.label}
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      onClick={onClose}
                      className={cn(
                        "group flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-[background-color,color,box-shadow] duration-150 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#803CE8] lg:min-h-10",
                        active
                          ? "bg-white/[0.10] font-semibold text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.04)]"
                          : "font-normal text-[#AEB8C5] hover:bg-white/[0.055] hover:text-white"
                      )}
                    >
                      <ProductIcon icon={Icon} active={active} />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="space-y-1 border-t border-white/10 bg-[#000A15] p-3">
        {canAccessAdmin && (
          <div className="px-3 py-1.5 text-slate-400 [&_*]:!text-slate-400">
            <SyncIndicator enabled={canAccessAdmin} />
          </div>
        )}

        {showLogin && (
          <LoginLink
            onNavigate={onClose}
            className="mb-1 w-full border-white/15 bg-white/[0.06] text-white hover:border-white/25 hover:bg-white/10 focus-visible:ring-[#803CE8] focus-visible:ring-offset-[#010D1B]"
          />
        )}

        {(canAccessAdmin || isDemoWorkspace) && (
          <Link
            href="/settings"
            onClick={onClose}
            aria-current={pathname.startsWith("/settings") ? "page" : undefined}
            className={cn(
              "group flex min-h-10 items-center gap-3 rounded-md px-3 py-2 text-[13px] transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#803CE8]",
              pathname.startsWith("/settings")
                ? "bg-white/[0.10] font-semibold text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.04)]"
                : "font-normal text-[#AEB8C5] hover:bg-white/[0.055] hover:text-white"
            )}
          >
            <ProductIcon
              icon={SettingsIcon}
              active={pathname.startsWith("/settings")}
            />
            Settings{!canAccessAdmin && <span className="sr-only"> (sign in as a demo administrator to manage settings)</span>}
          </Link>
        )}

        <div className="mt-2 border-t border-white/10 pt-3">
          <div className="px-3 pb-1.5 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Account
          </div>
          <Link
            href="/profile"
            onClick={onClose}
            aria-current={pathname.startsWith("/profile") ? "page" : undefined}
            className={cn(
              "group flex min-h-14 items-center gap-3 rounded-lg px-2.5 py-2 text-[13px] transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#803CE8]",
              pathname.startsWith("/profile")
                ? "bg-white/[0.09] text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.04)]"
                : "text-[#9AA5B3] hover:bg-white/[0.05] hover:text-white"
            )}
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-white/15 bg-white/[0.08] text-[11px] font-semibold text-white">
              {initials(isDemoFallback ? "Demo workspace" : me?.name)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-[#F2F5F8]">
                {isDemoFallback ? "Demo workspace" : me?.name || "My profile"}
              </span>
              <span className="mt-0.5 block truncate text-[11px] text-slate-500">
                {isDemoFallback ? "View demo profile" : me?.email || "View my profile"}
              </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-slate-400" aria-hidden="true" />
            <span className="sr-only">My profile</span>
          </Link>

          {showLogout && (
            <LogoutButton
              onNavigate={onClose}
              variant="ghost"
              size="sm"
              errorClassName="text-red-300"
              className="mt-1 w-full justify-start border-transparent px-2.5 text-slate-400 hover:bg-white/[0.035] hover:text-white focus-visible:ring-[#803CE8] focus-visible:ring-offset-[#010D1B]"
            />
          )}
        </div>
      </div>
    </aside>
  );
}
