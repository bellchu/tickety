export type NavigationVisibility = "all" | "admin" | "intelligence";

export type NavigationIconKey =
  | "dashboard"
  | "tickets"
  | "time"
  | "services"
  | "problems"
  | "changes"
  | "assets"
  | "knowledge"
  | "agents"
  | "email"
  | "surveys"
  | "leaderboard"
  | "reports"
  | "intelligence";

export interface NavigationItem {
  href: string;
  label: string;
  icon: NavigationIconKey;
  visibility: NavigationVisibility;
}

export interface NavigationSection {
  label: string;
  items: readonly NavigationItem[];
}

/**
 * Keep the workspace information architecture stable and directly scannable.
 * Sections organize the list without disclosure controls or hidden routes.
 */
export const navigationSections: readonly NavigationSection[] = [
  {
    label: "Work",
    items: [
      { href: "/", label: "Overview", icon: "dashboard", visibility: "all" },
      { href: "/tickets", label: "Tickets", icon: "tickets", visibility: "all" },
      { href: "/time", label: "My time", icon: "time", visibility: "all" },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/services", label: "Services", icon: "services", visibility: "all" },
      { href: "/problems", label: "Problems", icon: "problems", visibility: "all" },
      { href: "/changes", label: "Changes", icon: "changes", visibility: "all" },
      { href: "/assets", label: "Assets", icon: "assets", visibility: "all" },
      { href: "/knowledge", label: "Knowledge", icon: "knowledge", visibility: "all" },
    ],
  },
  {
    label: "Team",
    items: [
      { href: "/agents", label: "Agents", icon: "agents", visibility: "admin" },
      { href: "/email", label: "Email", icon: "email", visibility: "all" },
      { href: "/surveys", label: "Surveys", icon: "surveys", visibility: "all" },
      { href: "/leaderboard", label: "Leaderboard", icon: "leaderboard", visibility: "all" },
    ],
  },
  {
    label: "Insights",
    items: [
      { href: "/reports", label: "Reports", icon: "reports", visibility: "all" },
      {
        href: "/intelligence",
        label: "Intelligence",
        icon: "intelligence",
        visibility: "intelligence",
      },
    ],
  },
];

const utilityNavigationItems: readonly Pick<NavigationItem, "href" | "label">[] = [
  { href: "/settings/status", label: "Status" },
  { href: "/settings", label: "Settings" },
  { href: "/profile", label: "My profile" },
];

export function isNavigationItemActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function getCurrentNavigationItem(pathname: string) {
  const items = [
    ...navigationSections.flatMap((section) => section.items),
    ...utilityNavigationItems,
  ];

  return items
    .filter((item) => isNavigationItemActive(pathname, item.href))
    .sort((left, right) => right.href.length - left.href.length)[0];
}
