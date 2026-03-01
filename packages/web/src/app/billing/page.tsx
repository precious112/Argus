"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

interface PlanInfo {
  id: string;
  name: string;
  monthly_event_limit: number;
  max_team_members: number;
  max_api_keys: number;
  max_services: number;
  data_retention_days: number;
  conversation_retention_days: number;
  daily_ai_messages: number;
  webhook_enabled: boolean;
  custom_dashboards: boolean;
  external_alert_channels: boolean;
  audit_log: boolean;
  on_call_rotation: boolean;
  service_ownership: boolean;
}

interface UsageTier {
  up_to_events: number;
  price_dollars: number;
}

interface BillingStatus {
  plan: string;
  plan_name: string;
  team_members: { current: number; limit: number };
  api_keys: { current: number; limit: number };
  monthly_events: { current: number; limit: number };
  max_services: number;
  data_retention_days: number;
  features: Record<string, boolean>;
  subscription: {
    id: string;
    status: string;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
  } | null;
}

const apiBase = process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

function UsageBar({ current, limit, label }: { current: number; limit: number; label: string }) {
  const pct = limit > 0 ? Math.min((current / limit) * 100, 100) : 0;
  const limitText = limit < 0 ? "unlimited" : limit.toLocaleString();
  return (
    <div className="text-sm">
      <div className="flex justify-between text-xs text-[var(--muted)]">
        <span>{label}</span>
        <span>{current.toLocaleString()} / {limitText}</span>
      </div>
      <div className="mt-1 h-2 w-full rounded bg-[var(--border)]">
        <div
          className={`h-full rounded ${pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-yellow-500" : "bg-argus-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function CheckIcon() {
  return <span className="text-emerald-400">&#10003;</span>;
}

function XIcon() {
  return <span className="text-[var(--muted)]">&#10007;</span>;
}

export default function BillingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center p-8 text-[var(--muted)]">
          Loading billing...
        </div>
      }
    >
      <BillingContent />
    </Suspense>
  );
}

function BillingContent() {
  const searchParams = useSearchParams();
  const upgraded = searchParams.get("upgraded") === "true";

  const [plans, setPlans] = useState<PlanInfo[]>([]);
  const [usageTiers, setUsageTiers] = useState<UsageTier[]>([]);
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [plansRes, statusRes] = await Promise.all([
        fetch(`${apiBase}/api/v1/billing/plans`, { credentials: "include" }),
        fetch(`${apiBase}/api/v1/billing/status`, { credentials: "include" }),
      ]);
      if (plansRes.ok) {
        const data = await plansRes.json();
        setPlans(data.plans || []);
        setUsageTiers(data.usage_tiers || []);
      }
      if (statusRes.ok) {
        setStatus(await statusRes.json());
      }
    } catch {
      setError("Failed to load billing data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function handleUpgrade() {
    setCheckoutLoading(true);
    setError("");
    try {
      const res = await fetch(`${apiBase}/api/v1/billing/checkout`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to create checkout session");
        return;
      }
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch {
      setError("Failed to create checkout session");
    } finally {
      setCheckoutLoading(false);
    }
  }

  async function handleManageSubscription() {
    try {
      const res = await fetch(`${apiBase}/api/v1/billing/portal`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        const data = await res.json();
        if (data.portal_url) {
          window.open(data.portal_url, "_blank");
        }
      }
    } catch {
      setError("Failed to open subscription portal");
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-[var(--muted)]">
        Loading billing...
      </div>
    );
  }

  const freePlan = plans.find((p) => p.id === "free");
  const teamsPlan = plans.find((p) => p.id === "teams");
  const isTeams = status?.plan === "teams";
  const isCanceled = status?.subscription?.cancel_at_period_end;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <h1 className="text-xl font-semibold">Billing &amp; Plans</h1>

      {upgraded && (
        <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-400">
          Welcome to Teams! Your plan has been upgraded successfully.
        </div>
      )}

      {isCanceled && status?.subscription?.current_period_end && (
        <div className="rounded border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          Your Teams plan is canceled and will downgrade to Free at the end of the current period
          ({new Date(status.subscription.current_period_end).toLocaleDateString()}).
        </div>
      )}

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Current usage */}
      {status && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h2 className="mb-4 text-sm font-medium">
            Current Plan: <span className="text-argus-400">{status.plan_name}</span>
          </h2>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <UsageBar
              current={status.monthly_events.current}
              limit={status.monthly_events.limit}
              label="Monthly Events"
            />
            <UsageBar
              current={status.team_members.current}
              limit={status.team_members.limit}
              label="Team Members"
            />
            <UsageBar
              current={status.api_keys.current}
              limit={status.api_keys.limit}
              label="API Keys"
            />
            <div className="text-sm">
              <div className="text-xs text-[var(--muted)]">Data Retention</div>
              <div className="mt-1 font-medium">{status.data_retention_days} days</div>
            </div>
          </div>

          <div className="mt-4 flex gap-3">
            {isTeams ? (
              <button
                onClick={handleManageSubscription}
                className="rounded border border-[var(--border)] px-4 py-1.5 text-sm hover:bg-[var(--background)]"
              >
                Manage Subscription
              </button>
            ) : (
              <button
                onClick={handleUpgrade}
                disabled={checkoutLoading}
                className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500 disabled:opacity-50"
              >
                {checkoutLoading ? "Redirecting..." : "Upgrade to Teams — $25/mo"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Plan comparison */}
      {freePlan && teamsPlan && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <div className="border-b border-[var(--border)] px-4 py-3">
            <h2 className="text-sm font-medium">Plan Comparison</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
                <th className="px-4 py-2">Feature</th>
                <th className="px-4 py-2">Free</th>
                <th className="px-4 py-2">Teams ($25/mo)</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              <CompareRow label="Events/month" free="5,000" teams="100,000 (scalable)" />
              <CompareRow label="Data retention" free="3 days" teams="30 days" />
              <CompareRow label="Services" free="1" teams="10" />
              <CompareRow label="Team members" free="1" teams="10" />
              <CompareRow label="API keys" free="1" teams="10" />
              <CompareRow label="AI messages" free="10/day (BYOK)" teams="Unlimited (BYOK)" />
              <CompareRow label="Conversation history" free="3 days" teams="90 days" />
              <BoolCompareRow label="Webhook (full mode)" free={false} teams={true} />
              <BoolCompareRow label="Custom dashboards" free={false} teams={true} />
              <BoolCompareRow label="Slack/Discord/Email alerts" free={false} teams={true} />
              <BoolCompareRow label="Audit log" free={false} teams={true} />
              <BoolCompareRow label="On-call rotation" free={false} teams={true} />
              <BoolCompareRow label="Service ownership" free={false} teams={true} />
            </tbody>
          </table>
        </div>
      )}

      {/* Usage-based tiers */}
      {usageTiers.length > 0 && isTeams && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <div className="border-b border-[var(--border)] px-4 py-3">
            <h2 className="text-sm font-medium">Usage-Based Scaling (Teams)</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
                <th className="px-4 py-2">Events/month</th>
                <th className="px-4 py-2">Price</th>
              </tr>
            </thead>
            <tbody>
              {usageTiers.map((tier, i) => (
                <tr key={i} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2">Up to {tier.up_to_events.toLocaleString()}</td>
                  <td className="px-4 py-2">${tier.price_dollars}/mo</td>
                </tr>
              ))}
              <tr>
                <td className="px-4 py-2 text-[var(--muted)]">50M+</td>
                <td className="px-4 py-2 text-[var(--muted)]">Contact for Enterprise</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CompareRow({ label, free, teams }: { label: string; free: string; teams: string }) {
  return (
    <tr className="border-b border-[var(--border)] last:border-0">
      <td className="px-4 py-2">{label}</td>
      <td className="px-4 py-2 text-[var(--muted)]">{free}</td>
      <td className="px-4 py-2">{teams}</td>
    </tr>
  );
}

function BoolCompareRow({ label, free, teams }: { label: string; free: boolean; teams: boolean }) {
  return (
    <tr className="border-b border-[var(--border)] last:border-0">
      <td className="px-4 py-2">{label}</td>
      <td className="px-4 py-2">{free ? <CheckIcon /> : <XIcon />}</td>
      <td className="px-4 py-2">{teams ? <CheckIcon /> : <XIcon />}</td>
    </tr>
  );
}
