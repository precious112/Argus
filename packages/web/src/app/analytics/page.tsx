"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API =
  process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:7600/api/v1";

const COLORS = [
  "#6366f1", // indigo
  "#22d3ee", // cyan
  "#f59e0b", // amber
  "#ef4444", // red
  "#10b981", // emerald
  "#a855f7", // purple
  "#f97316", // orange
  "#14b8a6", // teal
];

const TIME_RANGES = [
  { label: "1h", hours: 1 },
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
  { label: "30d", hours: 720 },
];

interface BucketData {
  bucket: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  request_count: number;
}

interface DimensionData {
  name: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  request_count: number;
}

interface Summary {
  total_tokens: number;
  total_requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  avg_tokens_per_request: number;
  estimated_cost_usd: number;
  today_tokens: number;
  this_week_tokens: number;
  this_month_tokens: number;
}

function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(usd: number): string {
  if (usd < 0.01 && usd > 0) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function granularityForRange(hours: number): string {
  if (hours <= 6) return "hour";
  if (hours <= 168) return "day";
  return "day";
}

const tooltipStyle = {
  backgroundColor: "var(--card)",
  border: "1px solid var(--border)",
  borderRadius: "6px",
  fontSize: "12px",
};

export default function AnalyticsPage() {
  const [rangeHours, setRangeHours] = useState(24);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [usageData, setUsageData] = useState<BucketData[]>([]);
  const [providerData, setProviderData] = useState<DimensionData[]>([]);
  const [modelData, setModelData] = useState<DimensionData[]>([]);
  const [sourceData, setSourceData] = useState<DimensionData[]>([]);
  const [dailyData, setDailyData] = useState<BucketData[]>([]);
  const [budget, setBudget] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const gran = granularityForRange(rangeHours);
      const [summaryRes, usageRes, providerRes, modelRes, sourceRes, dailyRes, budgetRes] =
        await Promise.all([
          apiFetch(`${API}/analytics/summary`),
          apiFetch(`${API}/analytics/usage?granularity=${gran}&since_hours=${rangeHours}`),
          apiFetch(`${API}/analytics/breakdown?group_by=provider&since_hours=${rangeHours}`),
          apiFetch(`${API}/analytics/breakdown?group_by=model&since_hours=${rangeHours}`),
          apiFetch(`${API}/analytics/breakdown?group_by=source&since_hours=${rangeHours}`),
          apiFetch(`${API}/analytics/usage?granularity=day&since_hours=720`),
          apiFetch(`${API}/budget`),
        ]);

      const [summaryJ, usageJ, providerJ, modelJ, sourceJ, dailyJ, budgetJ] =
        await Promise.all([
          summaryRes.json(),
          usageRes.json(),
          providerRes.json(),
          modelRes.json(),
          sourceRes.json(),
          dailyRes.json(),
          budgetRes.json(),
        ]);

      setSummary(summaryJ);
      setUsageData(usageJ.data ?? []);
      setProviderData(providerJ.data ?? []);
      setModelData(modelJ.data ?? []);
      setSourceData(sourceJ.data ?? []);
      setDailyData(dailyJ.data ?? []);
      if (!budgetJ.error) setBudget(budgetJ);
    } catch {
      // silent - endpoints may not be available yet
    } finally {
      setLoading(false);
    }
  }, [rangeHours]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl p-8">
        <h2 className="mb-6 text-xl font-semibold">Token Usage Analytics</h2>
        <p className="text-[var(--muted)]">Loading...</p>
      </div>
    );
  }

  const hourlyPct =
    budget && budget.hourly_limit
      ? Math.min(100, Math.round(((budget.hourly_used || 0) / budget.hourly_limit) * 100))
      : 0;
  const dailyPct =
    budget && budget.daily_limit
      ? Math.min(100, Math.round(((budget.daily_used || 0) / budget.daily_limit) * 100))
      : 0;

  return (
    <div className="mx-auto max-w-7xl p-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-xl font-semibold">Token Usage Analytics</h2>
        <div className="flex gap-1 rounded-lg border border-[var(--border)] p-0.5">
          {TIME_RANGES.map((r) => (
            <button
              key={r.hours}
              onClick={() => setRangeHours(r.hours)}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                rangeHours === r.hours
                  ? "bg-[var(--accent)] text-white"
                  : "text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
          <SummaryCard label="Total Tokens" value={formatTokenCount(summary.total_tokens)} />
          <SummaryCard label="Today" value={formatTokenCount(summary.today_tokens)} />
          <SummaryCard label="Est. Cost" value={formatCost(summary.estimated_cost_usd)} />
          <SummaryCard
            label="Avg / Request"
            value={formatTokenCount(summary.avg_tokens_per_request)}
          />
        </div>
      )}

      {/* Budget Bars */}
      {budget && (budget.hourly_limit || budget.daily_limit) && (
        <div className="mb-6 grid grid-cols-2 gap-4">
          <BudgetBar
            label="Hourly"
            used={budget.hourly_used || 0}
            limit={budget.hourly_limit || 0}
            pct={hourlyPct}
          />
          <BudgetBar
            label="Daily"
            used={budget.daily_used || 0}
            limit={budget.daily_limit || 0}
            pct={dailyPct}
          />
        </div>
      )}

      {/* Charts Row 1 */}
      <div className="mb-6 grid gap-6 lg:grid-cols-5">
        {/* Usage Over Time - wider */}
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 lg:col-span-3">
          <h3 className="mb-3 text-sm font-medium text-[var(--foreground)]">
            Token Usage Over Time
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={usageData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="bucket"
                tick={{ fill: "var(--muted)", fontSize: 10 }}
                axisLine={{ stroke: "var(--border)" }}
                tickFormatter={(v) => {
                  if (v.length > 13) return v.slice(11, 16);
                  if (v.length > 10) return v.slice(5);
                  return v;
                }}
              />
              <YAxis
                tick={{ fill: "var(--muted)", fontSize: 10 }}
                axisLine={{ stroke: "var(--border)" }}
                tickFormatter={formatTokenCount}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value) => formatTokenCount(Number(value ?? 0))}
              />
              <Legend wrapperStyle={{ color: "var(--muted)", fontSize: 12 }} />
              <Area
                type="monotone"
                dataKey="prompt_tokens"
                stackId="1"
                stroke={COLORS[0]}
                fill={COLORS[0]}
                fillOpacity={0.4}
                name="Prompt"
              />
              <Area
                type="monotone"
                dataKey="completion_tokens"
                stackId="1"
                stroke={COLORS[1]}
                fill={COLORS[1]}
                fillOpacity={0.4}
                name="Completion"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* By Provider - Pie */}
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 lg:col-span-2">
          <h3 className="mb-3 text-sm font-medium text-[var(--foreground)]">By Provider</h3>
          {providerData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={providerData}
                  dataKey="total_tokens"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={90}
                  paddingAngle={2}
                  label={({ name }) => name}
                >
                  {providerData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value) => formatTokenCount(Number(value ?? 0))}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-[260px] items-center justify-center text-sm text-[var(--muted)]">
              No data
            </div>
          )}
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        {/* By Source */}
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h3 className="mb-3 text-sm font-medium text-[var(--foreground)]">By Source</h3>
          {sourceData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={sourceData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  type="number"
                  tick={{ fill: "var(--muted)", fontSize: 10 }}
                  axisLine={{ stroke: "var(--border)" }}
                  tickFormatter={formatTokenCount}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fill: "var(--muted)", fontSize: 10 }}
                  axisLine={{ stroke: "var(--border)" }}
                  width={100}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value) => formatTokenCount(Number(value ?? 0))}
                />
                <Bar dataKey="prompt_tokens" stackId="a" fill={COLORS[0]} name="Prompt" />
                <Bar dataKey="completion_tokens" stackId="a" fill={COLORS[1]} name="Completion" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-[220px] items-center justify-center text-sm text-[var(--muted)]">
              No data
            </div>
          )}
        </div>

        {/* By Model */}
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h3 className="mb-3 text-sm font-medium text-[var(--foreground)]">By Model</h3>
          {modelData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={modelData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  type="number"
                  tick={{ fill: "var(--muted)", fontSize: 10 }}
                  axisLine={{ stroke: "var(--border)" }}
                  tickFormatter={formatTokenCount}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fill: "var(--muted)", fontSize: 10 }}
                  axisLine={{ stroke: "var(--border)" }}
                  width={140}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value) => formatTokenCount(Number(value ?? 0))}
                />
                <Bar dataKey="prompt_tokens" stackId="a" fill={COLORS[0]} name="Prompt" />
                <Bar dataKey="completion_tokens" stackId="a" fill={COLORS[1]} name="Completion" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-[220px] items-center justify-center text-sm text-[var(--muted)]">
              No data
            </div>
          )}
        </div>
      </div>

      {/* Daily Totals - Full Width */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h3 className="mb-3 text-sm font-medium text-[var(--foreground)]">
          Daily Totals - Last 30 Days
        </h3>
        {dailyData.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="bucket"
                tick={{ fill: "var(--muted)", fontSize: 10 }}
                axisLine={{ stroke: "var(--border)" }}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis
                tick={{ fill: "var(--muted)", fontSize: 10 }}
                axisLine={{ stroke: "var(--border)" }}
                tickFormatter={formatTokenCount}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value) => formatTokenCount(Number(value ?? 0))}
              />
              <Legend wrapperStyle={{ color: "var(--muted)", fontSize: 12 }} />
              <Area
                type="monotone"
                dataKey="prompt_tokens"
                stackId="1"
                stroke={COLORS[4]}
                fill={COLORS[4]}
                fillOpacity={0.3}
                name="Prompt"
              />
              <Area
                type="monotone"
                dataKey="completion_tokens"
                stackId="1"
                stroke={COLORS[5]}
                fill={COLORS[5]}
                fillOpacity={0.3}
                name="Completion"
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-[220px] items-center justify-center text-sm text-[var(--muted)]">
            No data for the last 30 days
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function BudgetBar({
  label,
  used,
  limit,
  pct,
}: {
  label: string;
  used: number;
  limit: number;
  pct: number;
}) {
  const barColor = pct > 80 ? "bg-red-500" : pct > 50 ? "bg-yellow-500" : "bg-emerald-500";

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="mb-1.5 flex items-center justify-between text-sm">
        <span className="text-[var(--muted)]">{label} Budget</span>
        <span className="font-mono text-xs">
          {formatTokenCount(used)} / {formatTokenCount(limit)}
        </span>
      </div>
      <div className="h-3 rounded-full bg-[var(--border)]">
        <div
          className={`h-3 rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
