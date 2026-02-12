"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

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

interface ChartRendererProps {
  data: any;
}

export function ChartRenderer({ data }: ChartRendererProps) {
  const { chart_type, title } = data;

  return (
    <div className="rounded border border-[var(--border)] bg-[var(--card)] text-xs">
      {title && (
        <div className="border-b border-[var(--border)] px-3 py-1.5 font-medium text-[var(--foreground)]">
          {title}
        </div>
      )}
      <div className="p-3">
        {chart_type === "line" && <LineChart_ data={data} />}
        {chart_type === "bar" && <BarChart_ data={data} />}
        {chart_type === "pie" && <PieChart_ data={data} />}
      </div>
    </div>
  );
}

function LineChart_({ data }: { data: any }) {
  const xKey = data.x_key || "name";
  const yKeys: string[] = data.y_keys || ["value"];
  const unit = data.unit || "";
  const points = data.data || [];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={points}>
        <defs>
          {yKeys.map((key, i) => (
            <linearGradient key={key} id={`grad-${key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS[i % COLORS.length]} stopOpacity={0.3} />
              <stop offset="95%" stopColor={COLORS[i % COLORS.length]} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <XAxis
          dataKey={xKey}
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          axisLine={{ stroke: "var(--border)" }}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => `${v}${unit}`}
          width={45}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "6px",
            fontSize: "11px",
          }}
          labelStyle={{ color: "var(--muted)" }}
          formatter={(value) => [`${value}${unit}`]}
        />
        {yKeys.length > 1 && (
          <Legend
            wrapperStyle={{ fontSize: "11px", color: "var(--muted)" }}
          />
        )}
        {yKeys.map((key, i) => (
          <Area
            key={key}
            type="monotone"
            dataKey={key}
            stroke={COLORS[i % COLORS.length]}
            fill={`url(#grad-${key})`}
            strokeWidth={1.5}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

function BarChart_({ data }: { data: any }) {
  const xKey = data.x_key || "name";
  const yKeys: string[] = data.y_keys || ["value"];
  const unit = data.unit || "";
  const points = data.data || [];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={points}>
        <XAxis
          dataKey={xKey}
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          axisLine={{ stroke: "var(--border)" }}
          tickLine={false}
          angle={points.length > 8 ? -45 : 0}
          textAnchor={points.length > 8 ? "end" : "middle"}
          height={points.length > 8 ? 60 : 30}
        />
        <YAxis
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => `${v}${unit}`}
          width={45}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "6px",
            fontSize: "11px",
          }}
          labelStyle={{ color: "var(--muted)" }}
          formatter={(value) => [`${value}${unit}`]}
        />
        {yKeys.length > 1 && (
          <Legend
            wrapperStyle={{ fontSize: "11px", color: "var(--muted)" }}
          />
        )}
        {yKeys.map((key, i) => (
          <Bar
            key={key}
            dataKey={key}
            fill={COLORS[i % COLORS.length]}
            radius={[2, 2, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function PieChart_({ data }: { data: any }) {
  const nameKey = data.name_key || "name";
  const valueKey = data.value_key || "value";
  const points = data.data || [];
  const total = points.reduce((sum: number, d: any) => sum + (d[valueKey] || 0), 0);

  const renderLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, index }: any) => {
    const RADIAN = Math.PI / 180;
    const radius = outerRadius + 20;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);
    const item = points[index];
    const pct = total > 0 ? ((item[valueKey] / total) * 100).toFixed(1) : "0";

    return (
      <text
        x={x}
        y={y}
        fill="var(--muted)"
        textAnchor={x > cx ? "start" : "end"}
        dominantBaseline="central"
        fontSize={10}
      >
        {item[nameKey]} ({pct}%)
      </text>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={250}>
      <PieChart>
        <Pie
          data={points}
          dataKey={valueKey}
          nameKey={nameKey}
          cx="50%"
          cy="50%"
          outerRadius={80}
          label={renderLabel}
          labelLine={{ stroke: "var(--border)" }}
        >
          {points.map((_: any, i: number) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "6px",
            fontSize: "11px",
          }}
        />
        <Legend
          wrapperStyle={{ fontSize: "11px", color: "var(--muted)" }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
