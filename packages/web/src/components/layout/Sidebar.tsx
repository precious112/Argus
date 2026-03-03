"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useDeployment } from "@/hooks/useDeployment";
import { useLicense } from "@/hooks/useLicense";
import { editionLabel } from "@/lib/license";

const HIDDEN_PATHS = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/onboarding",
];

const STORAGE_KEY = "argus-sidebar-collapsed";

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
  saasOnly?: boolean;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

// --- Inline SVG icons (24x24, currentColor) ---

const IconChat = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const IconBell = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
);

const IconBarChart = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="20" x2="18" y2="10" />
    <line x1="12" y1="20" x2="12" y2="4" />
    <line x1="6" y1="20" x2="6" y2="14" />
  </svg>
);

const IconClock = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

const IconSearch = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

const IconServer = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
    <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
    <line x1="6" y1="6" x2="6.01" y2="6" />
    <line x1="6" y1="18" x2="6.01" y2="18" />
  </svg>
);

const IconWebhook = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 16.98h-5.99c-1.1 0-1.95.68-2.95 1.76C8.07 19.82 6.53 20.5 5 20.5c-2.49 0-4.5-2.01-4.5-4.5s2.01-4.5 4.5-4.5" />
    <path d="M12 2.5c2.49 0 4.5 2.01 4.5 4.5 0 1.53-.68 3.07-1.76 4.06-1.08 1-1.76 1.85-1.76 2.95V16" />
    <path d="M6 7.02h5.99c1.1 0 1.95-.68 2.95-1.76C15.93 4.18 17.47 3.5 19 3.5c2.49 0 4.5 2.01 4.5 4.5s-2.01 4.5-4.5 4.5" />
  </svg>
);

const IconArrowUp = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 19V5" />
    <path d="M5 12l7-7 7 7" />
  </svg>
);

const IconGear = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

const IconPeople = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);

const IconKey = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
  </svg>
);

const IconChip = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="4" y="4" width="16" height="16" rx="2" />
    <rect x="9" y="9" width="6" height="6" />
    <line x1="9" y1="1" x2="9" y2="4" />
    <line x1="15" y1="1" x2="15" y2="4" />
    <line x1="9" y1="20" x2="9" y2="23" />
    <line x1="15" y1="20" x2="15" y2="23" />
    <line x1="20" y1="9" x2="23" y2="9" />
    <line x1="20" y1="14" x2="23" y2="14" />
    <line x1="1" y1="9" x2="4" y2="9" />
    <line x1="1" y1="14" x2="4" y2="14" />
  </svg>
);

const IconPuzzle = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19.439 7.85c-.049.322.059.648.289.878l1.568 1.568c.47.47.706 1.087.706 1.704s-.235 1.233-.706 1.704l-1.611 1.611a.98.98 0 0 1-.837.276c-.47-.07-.802-.48-.968-.925a2.501 2.501 0 1 0-3.214 3.214c.446.166.855.497.925.968a.979.979 0 0 1-.276.837l-1.61 1.611a2.404 2.404 0 0 1-1.705.707 2.402 2.402 0 0 1-1.704-.706l-1.568-1.568a1.026 1.026 0 0 0-.877-.29c-.493.074-.84.504-1.02.968a2.5 2.5 0 1 1-3.237-3.237c.464-.18.894-.527.967-1.02a1.026 1.026 0 0 0-.289-.877l-1.568-1.568A2.402 2.402 0 0 1 1.998 12c0-.617.236-1.234.706-1.704L4.315 8.685a.98.98 0 0 1 .837-.276c.47.07.802.48.968.925a2.501 2.501 0 1 0 3.214-3.214c-.446-.166-.855-.497-.925-.968a.979.979 0 0 1 .276-.837l1.611-1.611a2.404 2.404 0 0 1 1.704-.706c.617 0 1.234.236 1.704.706l1.568 1.568c.23.23.556.338.877.29.493-.074.84-.504 1.02-.969a2.5 2.5 0 1 1 3.237 3.237c-.464.18-.894.527-.967 1.02z" />
  </svg>
);

const IconCreditCard = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
    <line x1="1" y1="10" x2="23" y2="10" />
  </svg>
);

const IconLogout = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <polyline points="16 17 21 12 16 7" />
    <line x1="21" y1="12" x2="9" y2="12" />
  </svg>
);

const IconChevronLeft = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="15 18 9 12 15 6" />
  </svg>
);

// --- Nav group definitions ---

const NAV_GROUPS: NavGroup[] = [
  {
    title: "MONITOR",
    items: [
      { label: "Chat", path: "/", icon: IconChat },
      { label: "Alerts", path: "/alerts", icon: IconBell },
      { label: "Analytics", path: "/analytics", icon: IconBarChart },
      { label: "History", path: "/history", icon: IconClock },
      { label: "Investigations", path: "/investigations", icon: IconSearch, saasOnly: true },
    ],
  },
  {
    title: "MANAGE",
    items: [
      { label: "Services", path: "/services", icon: IconServer },
      { label: "Webhooks", path: "/webhooks", icon: IconWebhook, saasOnly: true },
      { label: "Integrations", path: "/integrations", icon: IconPuzzle, saasOnly: true },
      { label: "Escalation", path: "/escalation", icon: IconArrowUp, saasOnly: true },
    ],
  },
  {
    title: "SETTINGS",
    items: [
      { label: "Settings", path: "/settings", icon: IconGear },
      { label: "Team", path: "/team", icon: IconPeople, saasOnly: true },
      { label: "API Keys", path: "/keys", icon: IconKey, saasOnly: true },
      { label: "LLM Keys", path: "/settings/llm", icon: IconChip, saasOnly: true },
      { label: "Billing", path: "/billing", icon: IconCreditCard, saasOnly: true },
    ],
  },
];

const EDITION_BADGE_COLORS: Record<string, string> = {
  pro: "bg-emerald-600/20 text-emerald-400",
  enterprise: "bg-violet-600/20 text-violet-400",
};

function isActive(pathname: string, itemPath: string): boolean {
  if (itemPath === "/") return pathname === "/";
  if (itemPath === "/settings") return pathname === "/settings";
  return pathname.startsWith(itemPath);
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { edition } = useLicense();
  const { isSaaS } = useDeployment();

  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "true") setCollapsed(true);
  }, []);

  // Hide sidebar on auth/onboarding pages
  if (HIDDEN_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return null;
  }

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  async function handleLogout() {
    await fetch(`${apiBase}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    router.push("/login");
  }

  function toggleCollapse() {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem(STORAGE_KEY, String(next));
  }

  const badgeColor = EDITION_BADGE_COLORS[edition];

  return (
    <aside
      className={`flex flex-col border-r border-[var(--border)] bg-[var(--background)] transition-[width] duration-200 ${
        collapsed ? "w-16" : "w-60"
      }`}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-[var(--border)] px-4">
        <img src="/argus-logo.png" alt="Argus" className="h-7 w-7 flex-shrink-0" />
        {!collapsed && (
          <span className="text-lg font-semibold tracking-tight">Argus</span>
        )}
      </div>

      {/* Nav groups */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {NAV_GROUPS.map((group) => {
          const visibleItems = group.items.filter(
            (item) => !item.saasOnly || isSaaS
          );
          if (visibleItems.length === 0) return null;

          return (
            <div key={group.title} className="mb-4">
              {!collapsed && (
                <div className="mb-1 px-2 text-[10px] font-semibold tracking-widest text-[var(--muted)]">
                  {group.title}
                </div>
              )}
              {visibleItems.map((item) => {
                const active = isActive(pathname, item.path);
                return (
                  <a
                    key={item.path}
                    href={item.path}
                    title={collapsed ? item.label : undefined}
                    className={`flex items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors ${
                      active
                        ? "bg-[var(--card)] text-[var(--foreground)]"
                        : "text-[var(--muted)] hover:bg-[var(--card)] hover:text-[var(--foreground)]"
                    } ${collapsed ? "justify-center" : ""}`}
                  >
                    <span className="flex-shrink-0">{item.icon}</span>
                    {!collapsed && <span>{item.label}</span>}
                  </a>
                );
              })}
            </div>
          );
        })}
      </nav>

      {/* Bottom section */}
      <div className="border-t border-[var(--border)] px-2 py-3 space-y-2">
        {/* Logout */}
        <button
          onClick={handleLogout}
          title={collapsed ? "Logout" : undefined}
          className={`flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm text-[var(--muted)] transition-colors hover:bg-[var(--card)] hover:text-[var(--foreground)] ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <span className="flex-shrink-0">{IconLogout}</span>
          {!collapsed && <span>Logout</span>}
        </button>

        {/* Collapse toggle */}
        <button
          onClick={toggleCollapse}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={`flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm text-[var(--muted)] transition-colors hover:bg-[var(--card)] hover:text-[var(--foreground)] ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <span
            className={`flex-shrink-0 transition-transform duration-200 ${
              collapsed ? "rotate-180" : ""
            }`}
          >
            {IconChevronLeft}
          </span>
          {!collapsed && <span>Collapse</span>}
        </button>

        {/* Version + edition badges */}
        {!collapsed && (
          <div className="flex items-center gap-2 px-2 pt-1">
            <span className="rounded bg-argus-600/20 px-2 py-0.5 text-[10px] text-argus-400">
              v0.1.0
            </span>
            {badgeColor && (
              <span
                className={`rounded px-2 py-0.5 text-[10px] font-medium ${badgeColor}`}
              >
                {editionLabel(edition)}
              </span>
            )}
            {isSaaS && (
              <span className="rounded bg-blue-600/20 px-2 py-0.5 text-[10px] text-blue-400">
                SaaS
              </span>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
