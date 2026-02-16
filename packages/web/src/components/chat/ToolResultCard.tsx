"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { ChartRenderer } from "./ChartRenderer";

interface ToolResultCardProps {
  displayType: string;
  data: any;
}

export function ToolResultCard({ displayType, data }: ToolResultCardProps) {
  if (data?.error) {
    return (
      <div className="rounded border border-red-800 bg-red-950/30 px-3 py-2 text-xs text-red-300">
        {data.error}
      </div>
    );
  }

  switch (displayType) {
    case "log_viewer":
      return <LogViewer data={data} />;
    case "metrics_chart":
      return <MetricsDisplay data={data} />;
    case "process_table":
      return <ProcessTable data={data} />;
    case "table":
      return <EventTable data={data} />;
    case "chart":
      return <ChartRenderer data={data} />;
    case "command_output":
      return <CommandOutput data={data} />;
    case "code_block":
      return <CodeBlock data={data} />;
    default:
      return <JsonTree data={data} />;
  }
}

function LogViewer({ data }: { data: any }) {
  const lines = data.matches || data.lines || [];
  const maxDisplay = 20;
  const displayed = lines.slice(0, maxDisplay);

  return (
    <div className="rounded border border-[var(--border)] bg-[#0d1117] text-xs">
      {data.file && (
        <div className="border-b border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
          {data.file}
          {data.total_matches != null && (
            <span className="ml-2">
              ({data.total_matches} match{data.total_matches !== 1 ? "es" : ""})
            </span>
          )}
        </div>
      )}
      <div className="max-h-64 overflow-auto p-1 font-mono">
        {displayed.map((item: any, i: number) => {
          // matches have context, lines are direct
          if (item.context) {
            return (
              <div key={i} className="mb-1 last:mb-0">
                {item.context.map((ctx: any, j: number) => (
                  <div
                    key={j}
                    className={`flex ${ctx.is_match ? "bg-yellow-900/30" : ""}`}
                  >
                    <span className="w-12 shrink-0 px-2 text-right text-[var(--muted)]">
                      {ctx.line_number}
                    </span>
                    <span className="whitespace-pre-wrap break-all text-gray-300">
                      {ctx.text}
                    </span>
                  </div>
                ))}
              </div>
            );
          }
          return (
            <div key={i} className="flex">
              <span className="w-12 shrink-0 px-2 text-right text-[var(--muted)]">
                {item.line_number}
              </span>
              <span className="whitespace-pre-wrap break-all text-gray-300">
                {item.text}
              </span>
            </div>
          );
        })}
      </div>
      {lines.length > maxDisplay && (
        <div className="border-t border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
          ... and {lines.length - maxDisplay} more
        </div>
      )}
    </div>
  );
}

function MetricsDisplay({ data }: { data: any }) {
  // Display current metrics or summary
  const entries = Object.entries(data).filter(
    ([k]) => !["display_type", "data_points", "time_range"].includes(k),
  );

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--card)] text-xs">
      {data.time_range && (
        <div className="border-b border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
          Time range: {data.time_range}
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 p-3">
        {entries.map(([key, value]) => {
          if (typeof value === "object" && value !== null) {
            // Nested object (like summary or metrics dict)
            const obj = value as Record<string, any>;
            return Object.entries(obj).map(([subKey, subVal]) => (
              <div key={`${key}.${subKey}`} className="flex justify-between">
                <span className="text-[var(--muted)]">
                  {key}.{subKey}
                </span>
                <span className="font-mono text-[var(--foreground)]">
                  {formatMetricValue(subKey, subVal)}
                </span>
              </div>
            ));
          }
          return (
            <div key={key} className="flex justify-between">
              <span className="text-[var(--muted)]">{key}</span>
              <span className="font-mono text-[var(--foreground)]">
                {formatMetricValue(key, value)}
              </span>
            </div>
          );
        })}
      </div>
      {data.data_points?.length >= 2 && (
        <div className="border-t border-[var(--border)] px-3 py-1.5">
          <ChartRenderer
            data={{
              chart_type: "line",
              title: "",
              x_key: "timestamp",
              y_keys: ["value"],
              unit: data.metric?.includes("percent") ? "%" : "",
              data: data.data_points,
            }}
          />
        </div>
      )}
    </div>
  );
}

function ProcessTable({ data }: { data: any }) {
  const items = data.processes || data.connections || [];
  const maxDisplay = 20;
  const displayed = items.slice(0, maxDisplay);

  if (data.connections) {
    return (
      <div className="rounded border border-[var(--border)] bg-[var(--card)] text-xs">
        <div className="max-h-64 overflow-auto">
          <table className="w-full">
            <thead className="bg-[var(--background)] text-[var(--muted)]">
              <tr>
                <th className="px-2 py-1 text-left">Local</th>
                <th className="px-2 py-1 text-left">Remote</th>
                <th className="px-2 py-1 text-left">Status</th>
                <th className="px-2 py-1 text-left">Process</th>
              </tr>
            </thead>
            <tbody>
              {displayed.map((conn: any, i: number) => (
                <tr
                  key={i}
                  className="border-t border-[var(--border)] text-[var(--foreground)]"
                >
                  <td className="px-2 py-1 font-mono">
                    {conn.local_addr}:{conn.local_port}
                  </td>
                  <td className="px-2 py-1 font-mono">
                    {conn.remote_addr
                      ? `${conn.remote_addr}:${conn.remote_port}`
                      : "-"}
                  </td>
                  <td className="px-2 py-1">{conn.status}</td>
                  <td className="px-2 py-1">{conn.process || conn.pid}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {items.length > maxDisplay && (
          <div className="border-t border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
            Showing {maxDisplay} of {items.length}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--card)] text-xs">
      <div className="max-h-64 overflow-auto">
        <table className="w-full">
          <thead className="bg-[var(--background)] text-[var(--muted)]">
            <tr>
              <th className="px-2 py-1 text-left">PID</th>
              <th className="px-2 py-1 text-left">Name</th>
              <th className="px-2 py-1 text-right">CPU %</th>
              <th className="px-2 py-1 text-right">MEM %</th>
              <th className="px-2 py-1 text-left">User</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((proc: any, i: number) => (
              <tr
                key={i}
                className="border-t border-[var(--border)] text-[var(--foreground)]"
              >
                <td className="px-2 py-1 font-mono">{proc.pid}</td>
                <td className="px-2 py-1">{proc.name}</td>
                <td className="px-2 py-1 text-right font-mono">
                  {(proc.cpu_percent ?? 0).toFixed(1)}
                </td>
                <td className="px-2 py-1 text-right font-mono">
                  {(proc.memory_percent ?? 0).toFixed(1)}
                </td>
                <td className="px-2 py-1">{proc.username}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length > maxDisplay && (
        <div className="border-t border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
          Showing {maxDisplay} of {items.length}
        </div>
      )}
    </div>
  );
}

function snakeToTitle(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatCellValue(value: any): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toFixed(2);
  }
  if (typeof value === "object") {
    const json = JSON.stringify(value);
    return json.length > 80 ? json.slice(0, 77) + "…" : json;
  }
  const s = String(value);
  // Detect ISO timestamps
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) {
    try {
      return new Date(s).toLocaleString();
    } catch {
      return s;
    }
  }
  return s.length > 100 ? s.slice(0, 97) + "…" : s;
}

function EventTable({ data }: { data: any }) {
  // Auto-detect the data array — check well-known keys first, then find any array
  const rows: any[] =
    data.events ||
    data.dependencies ||
    data.error_groups ||
    data.deploys ||
    data.slowest_spans ||
    Object.values(data).find((v) => Array.isArray(v)) ||
    [];

  const maxDisplay = 30;
  const displayed = rows.slice(0, maxDisplay);

  if (displayed.length === 0) {
    return (
      <div className="rounded border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs text-[var(--muted)]">
        No data found
      </div>
    );
  }

  // Auto-detect columns from the first row, cap at 6 for readability
  const allKeys = Object.keys(displayed[0]);
  const columns = allKeys.slice(0, 6);

  // Find a count-like summary field from the data object
  const countValue =
    data.count ?? data.total ?? data.total_count ?? null;

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--card)] text-xs">
      {countValue != null && (
        <div className="border-b border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
          {countValue} result{countValue !== 1 ? "s" : ""}
          {data.since_minutes ? ` in last ${data.since_minutes}m` : ""}
        </div>
      )}
      <div className="max-h-72 overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-[var(--background)] text-[var(--muted)]">
            <tr>
              {columns.map((col) => (
                <th key={col} className="px-2 py-1 text-left">
                  {snakeToTitle(col)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayed.map((row: any, i: number) => (
              <tr
                key={i}
                className="border-t border-[var(--border)] text-[var(--foreground)]"
              >
                {columns.map((col) => (
                  <td
                    key={col}
                    className="max-w-[200px] truncate px-2 py-1 font-mono"
                  >
                    {formatCellValue(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > maxDisplay && (
        <div className="border-t border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
          Showing {maxDisplay} of {rows.length}
        </div>
      )}
    </div>
  );
}

function CommandOutput({ data }: { data: any }) {
  const exitCode = data.exit_code ?? 0;
  const isError = exitCode !== 0;

  return (
    <div className="rounded border border-[var(--border)] bg-[#0d1117] text-xs">
      <div className="flex items-center gap-3 border-b border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
        <span className={isError ? "text-red-400" : "text-green-400"}>
          exit {exitCode}
        </span>
        {data.duration_ms != null && (
          <span>{data.duration_ms}ms</span>
        )}
      </div>
      {data.stdout && (
        <pre className="max-h-64 overflow-auto p-3 font-mono text-gray-300 whitespace-pre-wrap">
          {data.stdout}
        </pre>
      )}
      {data.stderr && (
        <pre className="max-h-32 overflow-auto border-t border-[var(--border)] p-3 font-mono text-red-400 whitespace-pre-wrap">
          {data.stderr}
        </pre>
      )}
      {!data.stdout && !data.stderr && (
        <div className="px-3 py-2 text-[var(--muted)]">No output</div>
      )}
    </div>
  );
}

function CodeBlock({ data }: { data: any }) {
  return (
    <div className="rounded border border-[var(--border)] bg-[#0d1117] text-xs">
      {data.path && (
        <div className="border-b border-[var(--border)] px-3 py-1.5 text-[var(--muted)]">
          {data.path}
          {data.total_lines && (
            <span className="ml-2">
              (lines {data.start_line}-{data.end_line} of {data.total_lines})
            </span>
          )}
        </div>
      )}
      <pre className="max-h-64 overflow-auto p-3 font-mono text-gray-300">
        {data.content}
      </pre>
    </div>
  );
}

function JsonTree({ data }: { data: any }) {
  const text =
    typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <pre className="max-h-48 overflow-auto rounded border border-[var(--border)] bg-[#0d1117] p-3 font-mono text-xs text-gray-300">
      {text}
    </pre>
  );
}

function formatMetricValue(key: string, value: any): string {
  if (typeof value !== "number") return String(value ?? "");
  if (key.includes("percent")) return `${value.toFixed(1)}%`;
  if (key.includes("_gb")) return `${value.toFixed(1)} GB`;
  if (key.includes("bytes_per_sec")) {
    if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB/s`;
    if (value > 1024) return `${(value / 1024).toFixed(1)} KB/s`;
    return `${value.toFixed(0)} B/s`;
  }
  if (key.includes("count")) return String(Math.round(value));
  return value.toFixed(2);
}
