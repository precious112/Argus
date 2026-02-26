"use client";

import { usePathname, useRouter } from "next/navigation";
import { useLicense } from "@/hooks/useLicense";
import { editionLabel } from "@/lib/license";

const EDITION_BADGE_COLORS: Record<string, string> = {
  pro: "bg-emerald-600/20 text-emerald-400",
  enterprise: "bg-violet-600/20 text-violet-400",
};

export function Header() {
  const pathname = usePathname();
  const router = useRouter();
  const { edition } = useLicense();

  // Don't render header on the login page
  if (pathname === "/login") return null;

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  async function handleLogout() {
    await fetch(`${apiBase}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    router.push("/login");
  }

  const badgeColor = EDITION_BADGE_COLORS[edition];

  return (
    <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
      <div className="flex items-center gap-3">
        <img src="/argus-logo.png" alt="Argus" className="h-7 w-auto" />
        <h1 className="text-lg font-semibold tracking-tight">Argus</h1>
        <span className="rounded bg-argus-600/20 px-2 py-0.5 text-xs text-argus-400">
          v0.1.0
        </span>
        {badgeColor && (
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${badgeColor}`}>
            {editionLabel(edition)}
          </span>
        )}
      </div>
      <nav className="flex items-center gap-4 text-sm text-[var(--muted)]">
        <a href="/" className="hover:text-[var(--foreground)]">
          Chat
        </a>
        <a href="/alerts" className="hover:text-[var(--foreground)]">
          Alerts
        </a>
        <a href="/services" className="hover:text-[var(--foreground)]">
          Services
        </a>
        <a href="/history" className="hover:text-[var(--foreground)]">
          History
        </a>
        <a href="/analytics" className="hover:text-[var(--foreground)]">
          Analytics
        </a>
        <a href="/settings" className="hover:text-[var(--foreground)]">
          Settings
        </a>
        <button
          onClick={handleLogout}
          className="rounded border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--card)] hover:text-[var(--foreground)]"
        >
          Logout
        </button>
      </nav>
    </header>
  );
}
