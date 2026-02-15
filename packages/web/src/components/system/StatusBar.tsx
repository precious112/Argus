"use client";

import type { BudgetStatus } from "@/lib/protocol";

interface SystemStatus {
  cpu_percent?: number;
  memory_percent?: number;
  memory_used_gb?: number;
  memory_total_gb?: number;
  disk_percent?: number;
  disk_free_gb?: number;
  load_avg?: string;
  cpu_count?: number;
}

interface StatusBarProps {
  status: SystemStatus | null;
  isConnected: boolean;
  budgetStatus?: BudgetStatus | null;
  mode?: string;
  servicesCount?: number;
}

function MetricBadge({
  label,
  value,
  warn,
  critical,
}: {
  label: string;
  value: string;
  warn?: boolean;
  critical?: boolean;
}) {
  const color = critical
    ? "text-red-400"
    : warn
      ? "text-yellow-400"
      : "text-[var(--muted)]";
  return (
    <div className="flex items-center gap-1.5">
      <span className={color}>
        {label}: {value}
      </span>
    </div>
  );
}

export function StatusBar({ status, isConnected, budgetStatus, mode, servicesCount }: StatusBarProps) {
  const cpu = status?.cpu_percent;
  const mem = status?.memory_percent;
  const disk = status?.disk_percent;
  const isSdkOnly = mode === "sdk_only";

  return (
    <div className="flex items-center gap-4 border-b border-[var(--border)] bg-[var(--card)] px-4 py-1.5 text-xs text-[var(--muted)]">
      <div className="flex items-center gap-1.5">
        <span
          className={`h-2 w-2 rounded-full ${
            isConnected ? "bg-green-500" : "bg-yellow-500"
          }`}
        />
        <span>Agent: {isConnected ? "Online" : "Connecting"}</span>
      </div>
      {isSdkOnly ? (
        <>
          <MetricBadge label="Mode" value="SDK-only" />
          {servicesCount != null && servicesCount > 0 && (
            <MetricBadge label="Services" value={String(servicesCount)} />
          )}
        </>
      ) : status ? (
        <>
          <MetricBadge
            label="CPU"
            value={cpu != null ? `${cpu.toFixed(0)}%` : "--"}
            warn={cpu != null && cpu > 80}
            critical={cpu != null && cpu > 95}
          />
          <MetricBadge
            label="Memory"
            value={
              mem != null
                ? `${mem.toFixed(0)}% (${status.memory_used_gb?.toFixed(1) ?? "?"}/${status.memory_total_gb?.toFixed(1) ?? "?"} GB)`
                : "--"
            }
            warn={mem != null && mem > 85}
            critical={mem != null && mem > 95}
          />
          <MetricBadge
            label="Disk"
            value={
              disk != null
                ? `${disk.toFixed(0)}% (${status.disk_free_gb?.toFixed(1) ?? "?"} GB free)`
                : "--"
            }
            warn={disk != null && disk > 85}
            critical={disk != null && disk > 95}
          />
          {status.load_avg && (
            <MetricBadge label="Load" value={status.load_avg} />
          )}
          {servicesCount != null && servicesCount > 0 && (
            <MetricBadge label="Services" value={String(servicesCount)} />
          )}
        </>
      ) : (
        <>
          <MetricBadge label="CPU" value="--" />
          <MetricBadge label="Memory" value="--" />
          <MetricBadge label="Disk" value="--" />
        </>
      )}
      {budgetStatus && (
        <MetricBadge
          label="AI Budget"
          value={`${budgetStatus.daily_pct.toFixed(0)}%`}
          warn={budgetStatus.daily_pct > 70}
          critical={budgetStatus.daily_pct > 90}
        />
      )}
    </div>
  );
}
