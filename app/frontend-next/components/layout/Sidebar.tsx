"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { SyncIndicator } from "@/components/layout/SyncIndicator";
import {
  BarChart3,
  TicketIcon,
  Radar,
  Trophy,
  User,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/",            label: "Dashboard",    icon: BarChart3 },
  { href: "/tickets",     label: "Tickets",      icon: TicketIcon },
  { href: "/intelligence", label: "Intelligence", icon: Radar },
  { href: "/leaderboard", label: "Leaderboard",  icon: Trophy },
];

export function Sidebar() {
  const pathname = usePathname();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.getMe });

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-56 flex-col border-r border-slate-200 bg-white">
      {/* Logo */}
      <div className="flex h-[50px] items-center px-4 border-b border-slate-100">
        <Link href="/" className="-ml-0.5">
          <TicketyLogo className="h-5" />
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-3 py-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                active
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Bottom section */}
      <div className="border-t border-slate-100 p-3 space-y-0.5">
        <div className="px-3 py-1.5">
          <SyncIndicator />
        </div>

        <Link
          href="/profile"
          className={cn(
            "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
            pathname.startsWith("/profile")
              ? "bg-slate-100 text-slate-900"
              : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
          )}
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-200 text-slate-600">
            <User className="h-3.5 w-3.5" />
          </div>
          <span className="flex-1 truncate">{me?.name || "Profile"}</span>
          {me && (
            <span className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
              T{me.tier}
            </span>
          )}
        </Link>

        <Link
          href="/settings"
          className={cn(
            "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
            pathname.startsWith("/settings")
              ? "bg-slate-100 text-slate-900"
              : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
          )}
        >
          <Settings className="h-4 w-4 shrink-0" />
          Settings
        </Link>
      </div>
    </aside>
  );
}
