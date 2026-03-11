"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useDeployment } from "@/hooks/useDeployment";

const DISMISS_KEY = "argus_upgrade_dismissed";
const DISMISS_DURATION_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const SHOW_DELAY_MS = 2000;

const apiBase = process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

export function UpgradePopup() {
  const { isSaaS, loading: deploymentLoading } = useDeployment();
  const router = useRouter();
  const [visible, setVisible] = useState(false);
  const checkedRef = useRef(false);

  useEffect(() => {
    if (deploymentLoading || !isSaaS || checkedRef.current) return;
    checkedRef.current = true;

    // Check localStorage dismissal
    const dismissed = localStorage.getItem(DISMISS_KEY);
    if (dismissed) {
      const elapsed = Date.now() - Number(dismissed);
      if (elapsed < DISMISS_DURATION_MS) return;
    }

    // Fetch billing status to check plan
    fetch(`${apiBase}/api/v1/billing/status`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.plan === "free") {
          setTimeout(() => setVisible(true), SHOW_DELAY_MS);
        }
      })
      .catch(() => {});
  }, [deploymentLoading, isSaaS]);

  if (!visible) return null;

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
    setVisible(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl">
        <h2 className="text-lg font-semibold">Unlock the full power of Argus</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Upgrade your plan to get access to:
        </p>
        <ul className="mt-3 space-y-2 text-sm">
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-emerald-400">&#10003;</span>
            Unlimited AI messages
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-emerald-400">&#10003;</span>
            30-day data retention
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-emerald-400">&#10003;</span>
            Team collaboration &amp; on-call escalation
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-emerald-400">&#10003;</span>
            100K+ events/month with overage credits
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-emerald-400">&#10003;</span>
            Webhooks, audit logging &amp; custom dashboards
          </li>
        </ul>
        <div className="mt-5 flex gap-3">
          <button
            onClick={() => router.push("/billing")}
            className="flex-1 rounded bg-argus-600 px-4 py-2 text-sm font-medium text-white hover:bg-argus-500"
          >
            Upgrade Now
          </button>
          <button
            onClick={dismiss}
            className="flex-1 rounded border border-[var(--border)] px-4 py-2 text-sm text-[var(--muted)] hover:bg-[var(--background)]"
          >
            Maybe Later
          </button>
        </div>
      </div>
    </div>
  );
}
