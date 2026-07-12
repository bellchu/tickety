"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { SyncIndicator } from "@/components/layout/SyncIndicator";
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
  Timer,
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
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.getMe });

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
          <TicketyLogo className="h-8" inverse />
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
        {navItems.map((item) => {
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
                "flex min-h-10 items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-clay-300",
                active
                  ? "bg-clay-500 text-white font-medium shadow-sm"
                  : "text-slate-300 hover:bg-white/[0.07] hover:text-white font-normal"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-0.5 border-t border-white/10 p-3">
        <div className="px-3 py-1.5 text-slate-400 [&_*]:!text-slate-400">
          <SyncIndicator />
        </div>

        <Link
          href="/profile"
          onClick={onClose}
          aria-current={pathname.startsWith("/profile") ? "page" : undefined}
          className={cn(
            "flex min-h-10 items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-clay-300",
            pathname.startsWith("/profile")
              ? "bg-clay-500 text-white font-medium"
              : "text-slate-300 hover:bg-white/[0.07] hover:text-white font-normal"
          )}
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-clay-400/20 text-clay-200">
            <User className="h-3.5 w-3.5" strokeWidth={1.5} />
          </div>
          <span className="flex-1 truncate">{me?.name || "Profile"}</span>
          {me && (
            <span className="rounded-full border border-white/15 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
              T{me.tier}
            </span>
          )}
        </Link>

        <Link
          href="/settings"
          onClick={onClose}
          aria-current={pathname.startsWith("/settings") ? "page" : undefined}
          className={cn(
            "flex min-h-10 items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-clay-300",
            pathname.startsWith("/settings")
              ? "bg-clay-500 text-white font-medium"
              : "text-slate-300 hover:bg-white/[0.07] hover:text-white font-normal"
          )}
        >
          <SettingsIcon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
          Settings
        </Link>
      </div>
    </aside>
  );
}
