"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { canAccessAdministration, canAccessProtectedIntelligence, isDemoContext } from "@/lib/auth";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { SyncIndicator } from "@/components/layout/SyncIndicator";
import { LoginLink } from "@/components/layout/LoginLink";
import { ProductIcon } from "@/components/icons/ProductIcon";
import {
  LayoutDashboard,
  Inbox,
  Users,
  BookOpen,
  BarChart3,
  TrendingUp,
  Settings as SettingsIcon,
  User,
  Radar,
  Package,
  AlertOctagon,
  GitBranch,
  Laptop,
  MessageSquareHeart,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/",             label: "Dashboard",    icon: LayoutDashboard },
  { href: "/tickets",      label: "Tickets",       icon: Inbox },
  { href: "/agents",       label: "Agents",        icon: Users },
  { href: "/services",     label: "Services",      icon: Package },
  { href: "/problems",     label: "Problems",      icon: AlertOctagon },
  { href: "/changes",      label: "Changes",       icon: GitBranch },
  { href: "/assets",       label: "Assets",        icon: Laptop },
  { href: "/knowledge",    label: "Knowledge Base", icon: BookOpen },
  { href: "/surveys",      label: "Surveys",       icon: MessageSquareHeart },
  { href: "/reports",      label: "Reports",       icon: BarChart3 },
  { href: "/leaderboard",  label: "Leaderboard",   icon: TrendingUp },
  { href: "/intelligence", label: "Intelligence",  icon: Radar },
];

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
  const showLogin = me?.auth_kind === "demo_fallback";

  return (
    <aside
      id="app-navigation"
      aria-label="Application navigation"
      aria-modal={open ? "true" : undefined}
      role={open ? "dialog" : undefined}
      className={cn(
        "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-white/10 bg-[#101820] text-white shadow-2xl transition-transform duration-200 ease-out lg:translate-x-0 lg:shadow-none",
        open ? "translate-x-0" : "-translate-x-full"
      )}
    >
      <div className="flex h-16 items-center justify-between border-b border-white/10 px-4">
        <Link href="/" className="-ml-0.5 rounded-md focus:outline-none focus:ring-2 focus:ring-clay-300" onClick={onClose}>
          <TicketyLogo inverse size="md" />
        </Link>
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-300 transition-colors hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-clay-300 lg:hidden"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="px-3 pt-6 pb-2">
        <span className="px-3 text-[10px] font-semibold tracking-[0.16em] text-slate-500">
          WORKSPACE
        </span>
      </div>

      <nav aria-label="Workspace" className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-4">
        {navItems.filter((item) => (
          (item.href !== "/intelligence" || canAccessIntelligence) &&
          (item.href !== "/agents" || canAccessAdmin)
        )).map((item) => {
          const Icon = item.icon;
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.label}
              href={item.href}
              aria-current={active ? "page" : undefined}
              onClick={onClose}
              className={cn(
                "group flex min-h-10 items-center gap-3 rounded-md px-3 py-2 text-[13px] transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#3D5AFE]",
                active
                  ? "font-medium text-[#F2F5F8]"
                  : "font-normal text-[#9AA5B3] hover:bg-white/[0.035] hover:text-[#E7EBF0]"
              )}
            >
              <ProductIcon icon={Icon} active={active} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-0.5 border-t border-white/10 p-3">
        {canAccessAdmin && (
          <div className="px-3 py-1.5 text-slate-400 [&_*]:!text-slate-400">
            <SyncIndicator enabled={canAccessAdmin} />
          </div>
        )}

        {showLogin && (
          <LoginLink
            onNavigate={onClose}
            className="mb-1 w-full border-white/15 bg-white/[0.06] text-white hover:border-white/25 hover:bg-white/10 focus-visible:ring-[#3D5AFE] focus-visible:ring-offset-[#101820]"
          />
        )}

        <Link
          href="/profile"
          onClick={onClose}
          aria-current={pathname.startsWith("/profile") ? "page" : undefined}
          className={cn(
            "group flex min-h-10 items-center gap-3 rounded-md px-3 py-2 text-[13px] transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#3D5AFE]",
            pathname.startsWith("/profile")
              ? "font-medium text-[#F2F5F8]"
              : "font-normal text-[#9AA5B3] hover:bg-white/[0.035] hover:text-[#E7EBF0]"
          )}
        >
          <ProductIcon icon={User} active={pathname.startsWith("/profile")} />
          <span className="flex-1 truncate">
            {isDemoWorkspace ? "Demo workspace" : me?.name || "Profile"}
          </span>
          {me && (
            <span className="rounded-full border border-white/15 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
              {isDemoWorkspace ? "DEMO" : `T${me.tier}`}
            </span>
          )}
        </Link>

        {(canAccessAdmin || isDemoWorkspace) && (
          <Link
            href="/settings"
            onClick={onClose}
            aria-current={pathname.startsWith("/settings") ? "page" : undefined}
            className={cn(
              "group flex min-h-10 items-center gap-3 rounded-md px-3 py-2 text-[13px] transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#3D5AFE]",
              pathname.startsWith("/settings")
                ? "font-medium text-[#F2F5F8]"
                : "font-normal text-[#9AA5B3] hover:bg-white/[0.035] hover:text-[#E7EBF0]"
            )}
          >
            <ProductIcon
              icon={SettingsIcon}
              active={pathname.startsWith("/settings")}
            />
            Settings{!canAccessAdmin && <span className="sr-only"> (sign in as a demo administrator to manage settings)</span>}
          </Link>
        )}
      </div>
    </aside>
  );
}
