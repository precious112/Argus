"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:7600/api/v1";

interface Alert {
  id: string;
  rule_name: string;
  severity: string;
  message: string;
  source: string;
  timestamp: string;
  resolved: boolean;
}

interface Investigation {
  alert_id: string;
  trigger: string;
  severity: string;
  timestamp: string;
  resolved: boolean;
}

type Tab = "alerts" | "investigations";

export default function HistoryPage() {
  const [tab, setTab] = useState<Tab>("alerts");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [severityFilter, setSeverityFilter] = useState("");
  const [resolvedFilter, setResolvedFilter] = useState<string>("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const PAGE_SIZE = 50;

  const fetchAlerts = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (severityFilter) params.set("severity", severityFilter);
      if (resolvedFilter) params.set("resolved", resolvedFilter);
      params.set("page", String(page));
      params.set("page_size", String(PAGE_SIZE));
      const resp = await apiFetch(`${API_BASE}/alerts?${params}`);
      const data = await resp.json();
      setAlerts(data.alerts || []);
      setTotal(data.total ?? data.count ?? 0);
      setTotalPages(data.total_pages ?? 1);
    } catch {
      /* ignore */
    }
  }, [severityFilter, resolvedFilter, page]);

  const fetchInvestigations = useCallback(async () => {
    try {
      const resp = await apiFetch(`${API_BASE}/investigations`);
      const data = await resp.json();
      setInvestigations(data.investigations || []);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (tab === "alerts") fetchAlerts();
    else fetchInvestigations();
  }, [tab, fetchAlerts, fetchInvestigations]);

  return (
    <div className="mx-auto max-w-3xl p-8">
      <h2 className="mb-6 text-xl font-semibold text-[var(--foreground)]">
        History
      </h2>

      {/* Tabs */}
      <div className="mb-4 flex gap-2 border-b border-[var(--border)]">
        {(["alerts", "investigations"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setPage(1); }}
            className={`px-4 py-2 text-sm font-medium capitalize transition-colors ${
              tab === t
                ? "border-b-2 border-argus-500 text-[var(--foreground)]"
                : "text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Filters for alerts */}
      {tab === "alerts" && (
        <div className="mb-4 flex gap-3 text-xs">
          <select
            value={severityFilter}
            onChange={(e) => { setSeverityFilter(e.target.value); setPage(1); }}
            className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-[var(--foreground)]"
          >
            <option value="">All severities</option>
            <option value="URGENT">Urgent</option>
            <option value="NOTABLE">Notable</option>
          </select>
          <select
            value={resolvedFilter}
            onChange={(e) => { setResolvedFilter(e.target.value); setPage(1); }}
            className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-[var(--foreground)]"
          >
            <option value="">All statuses</option>
            <option value="false">Active</option>
            <option value="true">Resolved</option>
          </select>
          <span className="text-[var(--muted)]">
            {total > 0
              ? `${(page - 1) * PAGE_SIZE + 1}\u2013${Math.min(page * PAGE_SIZE, total)} of ${total}`
              : "0 alerts"}
          </span>
        </div>
      )}

      {/* Content */}
      {tab === "alerts" && (
        <div className="space-y-2">
          {alerts.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No alerts found.</p>
          ) : (
            alerts.map((alert) => (
              <div
                key={alert.id}
                className={`rounded-lg border px-4 py-3 text-sm ${
                  alert.severity === "URGENT"
                    ? "border-red-800 bg-red-900/20"
                    : "border-yellow-800 bg-yellow-900/20"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        alert.severity === "URGENT"
                          ? "bg-red-500"
                          : "bg-yellow-500"
                      }`}
                    />
                    <span className="font-medium text-[var(--foreground)]">
                      {alert.rule_name}
                    </span>
                    {alert.resolved && (
                      <span className="rounded bg-green-900/30 px-1.5 py-0.5 text-xs text-green-400">
                        Resolved
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-[var(--muted)]">
                    {new Date(alert.timestamp).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  {alert.message}
                </p>
              </div>
            ))
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-2 text-sm">
              <span className="text-[var(--muted)]">
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="rounded border border-[var(--border)] px-3 py-1 text-[var(--foreground)] hover:bg-[var(--card)] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Prev
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="rounded border border-[var(--border)] px-3 py-1 text-[var(--foreground)] hover:bg-[var(--card)] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "investigations" && (
        <div className="space-y-2">
          {investigations.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">
              No investigations found.
            </p>
          ) : (
            investigations.map((inv) => (
              <div
                key={inv.alert_id}
                className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-[var(--foreground)]">
                    {inv.trigger}
                  </span>
                  <span className="text-xs text-[var(--muted)]">
                    {new Date(inv.timestamp).toLocaleString()}
                  </span>
                </div>
                <div className="mt-1 flex gap-2 text-xs">
                  <span
                    className={
                      inv.severity === "URGENT"
                        ? "text-red-400"
                        : "text-yellow-400"
                    }
                  >
                    {inv.severity}
                  </span>
                  {inv.resolved && (
                    <span className="text-green-400">Resolved</span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
