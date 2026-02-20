"use client";

import { useEffect, useState } from "react";

interface MetricBucket {
  bucket: string;
  invocation_count: number;
  error_count: number;
  error_rate: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  p99_duration_ms: number;
  cold_start_count: number;
  cold_start_pct: number;
}

interface ErrorGroup {
  error_type: string;
  error_message: string;
  count: number;
  first_seen: string;
  last_seen: string;
  service: string;
}

interface ServiceMetricsPanelProps {
  service: string;
  apiBase: string;
}

export function ServiceMetricsPanel({
  service,
  apiBase,
}: ServiceMetricsPanelProps) {
  const [metrics, setMetrics] = useState<MetricBucket[]>([]);
  const [errors, setErrors] = useState<ErrorGroup[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(
          `${apiBase}/api/v1/services/${encodeURIComponent(service)}/metrics?since_minutes=60`,
        );
        const data = await res.json();
        setMetrics(data.metrics || []);
        setErrors(data.error_groups || []);
      } catch {
        // ignore fetch errors
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [service, apiBase]);

  if (loading) {
    return <div className="p-4 text-sm text-[var(--muted)]">Loading...</div>;
  }

  // Compute summary stats
  const totalInvocations = metrics.reduce(
    (sum, b) => sum + b.invocation_count,
    0,
  );
  const totalErrors = metrics.reduce((sum, b) => sum + b.error_count, 0);
  const avgP95 =
    metrics.length > 0
      ? metrics.reduce((sum, b) => sum + b.p95_duration_ms, 0) / metrics.length
      : 0;
  const totalColdStarts = metrics.reduce(
    (sum, b) => sum + b.cold_start_count,
    0,
  );

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">{service} - Metrics (Last 1h)</h2>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        <SummaryCard label="Invocations" value={totalInvocations.toLocaleString()} />
        <SummaryCard
          label="Error Rate"
          value={
            totalInvocations > 0
              ? `${((totalErrors / totalInvocations) * 100).toFixed(1)}%`
              : "0%"
          }
          warn={totalErrors > 0}
        />
        <SummaryCard label="Avg P95 Latency" value={`${avgP95.toFixed(0)}ms`} />
        <SummaryCard label="Cold Starts" value={totalColdStarts.toLocaleString()} />
      </div>

      {/* Metrics timeline table */}
      {metrics.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--border)] text-[var(--muted)]">
                <th className="px-2 py-1 text-left">Time</th>
                <th className="px-2 py-1 text-right">Invocations</th>
                <th className="px-2 py-1 text-right">Errors</th>
                <th className="px-2 py-1 text-right">Error %</th>
                <th className="px-2 py-1 text-right">P50</th>
                <th className="px-2 py-1 text-right">P95</th>
                <th className="px-2 py-1 text-right">P99</th>
                <th className="px-2 py-1 text-right">Cold %</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((b, i) => (
                <tr key={i} className="border-b border-[var(--border)]">
                  <td className="px-2 py-1">
                    {new Date(b.bucket).toLocaleTimeString()}
                  </td>
                  <td className="px-2 py-1 text-right">{b.invocation_count}</td>
                  <td
                    className={`px-2 py-1 text-right ${
                      b.error_count > 0 ? "text-red-400" : ""
                    }`}
                  >
                    {b.error_count}
                  </td>
                  <td
                    className={`px-2 py-1 text-right ${
                      b.error_rate > 5 ? "text-red-400" : ""
                    }`}
                  >
                    {b.error_rate}%
                  </td>
                  <td className="px-2 py-1 text-right">{b.p50_duration_ms.toFixed(0)}ms</td>
                  <td className="px-2 py-1 text-right">{b.p95_duration_ms.toFixed(0)}ms</td>
                  <td className="px-2 py-1 text-right">{b.p99_duration_ms.toFixed(0)}ms</td>
                  <td className="px-2 py-1 text-right">{b.cold_start_pct.toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Error groups */}
      {errors.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold">Error Groups</h3>
          <div className="space-y-2">
            {errors.map((e, i) => (
              <div
                key={i}
                className="rounded border border-red-900/30 bg-red-950/20 p-3 text-xs"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-red-400">{e.error_type}</span>
                  <span className="text-[var(--muted)]">{e.count}x</span>
                </div>
                <p className="mt-1 text-[var(--muted)]">{e.error_message}</p>
                <p className="mt-1 text-[var(--muted)]">
                  Last seen: {new Date(e.last_seen).toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {metrics.length === 0 && errors.length === 0 && (
        <p className="text-sm text-[var(--muted)]">No metrics data available yet.</p>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="text-xs text-[var(--muted)]">{label}</div>
      <div
        className={`text-xl font-bold ${warn ? "text-red-400" : "text-[var(--foreground)]"}`}
      >
        {value}
      </div>
    </div>
  );
}
