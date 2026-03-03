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

interface PlanPricing {
  [planId: string]: { monthly: number; annual: number };
}

interface PaygInfo {
  enabled: boolean;
  budget_dollars: number;
  spent_dollars: number;
  remaining_dollars: number;
  overage_events: number;
  rate_per_1k_dollars: number;
}

interface BillingStatus {
  plan: string;
  plan_name: string;
  team_members: { current: number; limit: number };
  api_keys: { current: number; limit: number };
  monthly_events: { current: number; limit: number };
  max_services: number;
  data_retention_days: number;
  billing_period_start: string | null;
  billing_period_end: string | null;
  payg: {
    enabled: boolean;
    budget_cents: number;
    spent_cents: number;
    overage_events: number;
    rate_per_1k_cents: number;
  };
  features: Record<string, boolean>;
  subscription: {
    id: string;
    status: string;
    plan_id: string;
    billing_interval: string;
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
  const [pricing, setPricing] = useState<PlanPricing>({});
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [paygStatus, setPaygStatus] = useState<PaygInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState("");
  const [billingInterval, setBillingInterval] = useState<"month" | "year">("month");
  const [paygBudget, setPaygBudget] = useState("");
  const [paygSaving, setPaygSaving] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [plansRes, statusRes, paygRes] = await Promise.all([
        fetch(`${apiBase}/api/v1/billing/plans`, { credentials: "include" }),
        fetch(`${apiBase}/api/v1/billing/status`, { credentials: "include" }),
        fetch(`${apiBase}/api/v1/billing/payg`, { credentials: "include" }),
      ]);
      if (plansRes.ok) {
        const data = await plansRes.json();
        setPlans(data.plans || []);
        setPricing(data.pricing || {});
      }
      if (statusRes.ok) {
        setStatus(await statusRes.json());
      }
      if (paygRes.ok) {
        setPaygStatus(await paygRes.json());
      }
    } catch {
      setError("Failed to load billing data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (paygStatus) {
      setPaygBudget(paygStatus.budget_dollars > 0 ? paygStatus.budget_dollars.toString() : "");
    }
  }, [paygStatus]);

  async function handleCheckout(planId: string) {
    setCheckoutLoading(planId);
    setError("");
    try {
      const res = await fetch(`${apiBase}/api/v1/billing/checkout`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: planId, billing_interval: billingInterval }),
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
      setCheckoutLoading("");
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

  async function handleSavePayg() {
    setPaygSaving(true);
    setError("");
    try {
      const budgetDollars = paygBudget ? parseFloat(paygBudget) : 0;
      const res = await fetch(`${apiBase}/api/v1/billing/payg`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ budget_dollars: budgetDollars }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to update PAYG settings");
        return;
      }
      const data = await res.json();
      setPaygStatus(data);
      fetchData();
    } catch {
      setError("Failed to update PAYG settings");
    } finally {
      setPaygSaving(false);
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
  const businessPlan = plans.find((p) => p.id === "business");
  const currentPlan = status?.plan || "free";
  const isPaid = currentPlan === "teams" || currentPlan === "business";
  const isCanceled = status?.subscription?.cancel_at_period_end;

  const eventUsagePct = status
    ? Math.min((status.monthly_events.current / status.monthly_events.limit) * 100, 100)
    : 0;
  const paygActive = status?.payg?.enabled && status.monthly_events.current > status.monthly_events.limit;

  function planPrice(planId: string): string {
    const p = pricing[planId];
    if (!p) return "$0";
    if (billingInterval === "year") return `$${p.annual}/yr`;
    return `$${p.monthly}/mo`;
  }

  function planPriceLabel(planId: string): string {
    const p = pricing[planId];
    if (!p) return "Free";
    if (billingInterval === "year") {
      return `$${p.annual}/yr (Save 20%)`;
    }
    return `$${p.monthly}/mo`;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <h1 className="text-xl font-semibold">Billing &amp; Plans</h1>

      {upgraded && (
        <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-400">
          Your plan has been upgraded successfully!
        </div>
      )}

      {isCanceled && status?.subscription?.current_period_end && (
        <div className="rounded border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          Your plan is canceled and will downgrade to Free at the end of the current period
          ({new Date(status.subscription.current_period_end).toLocaleDateString()}).
        </div>
      )}

      {/* Usage warning banners */}
      {status && eventUsagePct >= 80 && eventUsagePct < 100 && (
        <div className="rounded border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          You&apos;ve used {Math.round(eventUsagePct)}% of your monthly events
          ({status.monthly_events.current.toLocaleString()}/{status.monthly_events.limit.toLocaleString()}).
        </div>
      )}
      {status && eventUsagePct >= 100 && paygActive && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          Plan quota exceeded — PAYG active (${(status.payg.spent_cents / 100).toFixed(2)} spent on overages).
        </div>
      )}
      {status && eventUsagePct >= 100 && !status.payg.enabled && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          Monthly event limit reached — events are being rejected.
          {isPaid ? " Enable Pay-As-You-Go below to continue ingesting." : " Upgrade your plan for higher limits."}
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
            {status.subscription?.billing_interval === "year" && (
              <span className="ml-2 text-xs text-[var(--muted)]">(Annual)</span>
            )}
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

          {status.billing_period_start && (
            <div className="mt-3 text-xs text-[var(--muted)]">
              Billing period: {new Date(status.billing_period_start).toLocaleDateString()}
              {status.billing_period_end && ` — ${new Date(status.billing_period_end).toLocaleDateString()}`}
            </div>
          )}

          <div className="mt-4 flex gap-3">
            {isPaid && (
              <button
                onClick={handleManageSubscription}
                className="rounded border border-[var(--border)] px-4 py-1.5 text-sm hover:bg-[var(--background)]"
              >
                Manage Subscription
              </button>
            )}
            {currentPlan === "free" && (
              <>
                <button
                  onClick={() => handleCheckout("teams")}
                  disabled={!!checkoutLoading}
                  className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500 disabled:opacity-50"
                >
                  {checkoutLoading === "teams" ? "Redirecting..." : `Upgrade to Teams — ${planPrice("teams")}`}
                </button>
                <button
                  onClick={() => handleCheckout("business")}
                  disabled={!!checkoutLoading}
                  className="rounded border border-argus-600 px-4 py-1.5 text-sm font-medium text-argus-400 hover:bg-argus-600/10 disabled:opacity-50"
                >
                  {checkoutLoading === "business" ? "Redirecting..." : `Upgrade to Business — ${planPrice("business")}`}
                </button>
              </>
            )}
            {currentPlan === "teams" && (
              <button
                onClick={() => handleCheckout("business")}
                disabled={!!checkoutLoading}
                className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500 disabled:opacity-50"
              >
                {checkoutLoading === "business" ? "Redirecting..." : `Upgrade to Business — ${planPrice("business")}`}
              </button>
            )}
          </div>
        </div>
      )}

      {/* PAYG settings (paid plans only) */}
      {isPaid && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h2 className="mb-1 text-sm font-medium">Pay-As-You-Go (PAYG)</h2>
          <p className="mb-4 text-xs text-[var(--muted)]">
            Events beyond your plan quota are charged at $0.30 per 1,000 events.
            Set a monthly spending cap to control costs.
          </p>

          {paygStatus && paygStatus.enabled && (
            <div className="mb-4">
              <UsageBar
                current={Math.round(paygStatus.spent_dollars * 100)}
                limit={Math.round(paygStatus.budget_dollars * 100)}
                label={`PAYG Spend: $${paygStatus.spent_dollars.toFixed(2)} / $${paygStatus.budget_dollars.toFixed(2)}`}
              />
              <div className="mt-1 text-xs text-[var(--muted)]">
                {paygStatus.overage_events.toLocaleString()} overage events
              </div>
            </div>
          )}

          <div className="flex items-end gap-3">
            <div>
              <label className="mb-1 block text-xs text-[var(--muted)]">Monthly budget ($)</label>
              <input
                type="number"
                min="0"
                step="1"
                placeholder="e.g. 10"
                value={paygBudget}
                onChange={(e) => setPaygBudget(e.target.value)}
                className="w-32 rounded border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-sm"
              />
            </div>
            <button
              onClick={handleSavePayg}
              disabled={paygSaving}
              className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500 disabled:opacity-50"
            >
              {paygSaving ? "Saving..." : paygBudget && parseFloat(paygBudget) > 0 ? "Enable PAYG" : "Disable PAYG"}
            </button>
          </div>
        </div>
      )}

      {/* Billing interval toggle */}
      <div className="flex items-center justify-center gap-3">
        <span className={`text-sm ${billingInterval === "month" ? "text-white" : "text-[var(--muted)]"}`}>Monthly</span>
        <button
          onClick={() => setBillingInterval(billingInterval === "month" ? "year" : "month")}
          className={`relative h-6 w-11 rounded-full transition-colors ${billingInterval === "year" ? "bg-argus-600" : "bg-[var(--border)]"}`}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${billingInterval === "year" ? "translate-x-5" : "translate-x-0.5"}`}
          />
        </button>
        <span className={`text-sm ${billingInterval === "year" ? "text-white" : "text-[var(--muted)]"}`}>
          Annual <span className="text-emerald-400 text-xs">(Save 20%)</span>
        </span>
      </div>

      {/* Plan comparison */}
      {freePlan && teamsPlan && businessPlan && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <div className="border-b border-[var(--border)] px-4 py-3">
            <h2 className="text-sm font-medium">Plan Comparison</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
                <th className="px-4 py-2">Feature</th>
                <th className="px-4 py-2">Free</th>
                <th className="px-4 py-2">Teams ({planPriceLabel("teams")})</th>
                <th className="px-4 py-2">Business ({planPriceLabel("business")})</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              <CompareRow3 label="Events/month" free="5,000" teams="100,000" business="300,000" />
              <CompareRow3 label="Data retention" free="3 days" teams="30 days" business="90 days" />
              <CompareRow3 label="Services" free="1" teams="10" business="30" />
              <CompareRow3 label="Team members" free="1" teams="10" business="30" />
              <CompareRow3 label="API keys" free="1" teams="10" business="30" />
              <CompareRow3 label="AI messages" free="10/day (BYOK)" teams="Unlimited (BYOK)" business="Unlimited (BYOK)" />
              <CompareRow3 label="Conversation history" free="3 days" teams="90 days" business="270 days" />
              <CompareRow3 label="PAYG overages" free="-" teams="$0.30/1K events" business="$0.30/1K events" />
              <BoolCompareRow3 label="Webhook (full mode)" free={false} teams={true} business={true} />
              <BoolCompareRow3 label="Custom dashboards" free={false} teams={true} business={true} />
              <BoolCompareRow3 label="Slack/Discord/Email alerts" free={false} teams={true} business={true} />
              <BoolCompareRow3 label="Audit log" free={false} teams={true} business={true} />
              <BoolCompareRow3 label="On-call rotation" free={false} teams={true} business={true} />
              <BoolCompareRow3 label="Service ownership" free={false} teams={true} business={true} />
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CompareRow3({ label, free, teams, business }: { label: string; free: string; teams: string; business: string }) {
  return (
    <tr className="border-b border-[var(--border)] last:border-0">
      <td className="px-4 py-2">{label}</td>
      <td className="px-4 py-2 text-[var(--muted)]">{free}</td>
      <td className="px-4 py-2">{teams}</td>
      <td className="px-4 py-2">{business}</td>
    </tr>
  );
}

function BoolCompareRow3({ label, free, teams, business }: { label: string; free: boolean; teams: boolean; business: boolean }) {
  return (
    <tr className="border-b border-[var(--border)] last:border-0">
      <td className="px-4 py-2">{label}</td>
      <td className="px-4 py-2">{free ? <CheckIcon /> : <XIcon />}</td>
      <td className="px-4 py-2">{teams ? <CheckIcon /> : <XIcon />}</td>
      <td className="px-4 py-2">{business ? <CheckIcon /> : <XIcon />}</td>
    </tr>
  );
}
