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
  Globe,
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

export function Sidebar() {
  const pathname = usePathname();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.getMe });

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-linen-50 border-r border-linen-300">
      <div className="flex items-center px-4 h-[60px] border-b border-linen-300">
        <Link href="/" className="-ml-0.5">
          <TicketyLogo className="h-8" />
        </Link>
      </div>

      <div className="px-3 pt-6 pb-2">
        <span className="px-3 text-[10px] font-semibold tracking-wider text-ink-400">
          WORKSPACE
        </span>
      </div>

      <nav className="flex-1 space-y-0.5 px-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.label}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors",
                active
                  ? "bg-linen-300 text-ink-700 font-medium"
                  : "text-ink-500 hover:bg-linen-200 hover:text-ink-600 font-normal"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-linen-300 p-3 space-y-0.5">
        <div className="px-3 py-1.5">
          <SyncIndicator />
        </div>

        <Link
          href="/profile"
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors",
            pathname.startsWith("/profile")
              ? "bg-linen-300 text-ink-700 font-medium"
              : "text-ink-500 hover:bg-linen-200 hover:text-ink-600 font-normal"
          )}
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-clay-400/15 text-clay-500">
            <User className="h-3.5 w-3.5" strokeWidth={1.5} />
          </div>
          <span className="flex-1 truncate">{me?.name || "Profile"}</span>
          {me && (
            <span className="rounded-full border border-linen-400 px-1.5 py-0.5 text-[10px] font-medium text-ink-400">
              T{me.tier}
            </span>
          )}
        </Link>

        <Link
          href="/settings"
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors",
            pathname.startsWith("/settings")
              ? "bg-linen-300 text-ink-700 font-medium"
              : "text-ink-500 hover:bg-linen-200 hover:text-ink-600 font-normal"
          )}
        >
          <SettingsIcon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
          Settings
        </Link>
      </div>
    </aside>
  );
}