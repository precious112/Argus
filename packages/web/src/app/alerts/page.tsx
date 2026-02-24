"use client";

import { useCallback, useEffect, useState } from "react";

interface AlertItem {
  id: string;
  rule_id: string;
  rule_name: string;
  severity: string;
  message: string;
  source: string;
  event_type: string;
  timestamp: string;
  resolved: boolean;
  resolved_at: string | null;
  status: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
}

interface RuleItem {
  id: string;
  name: string;
  event_types: string[];
  min_severity: string;
  max_severity: string | null;
  cooldown_seconds: number;
  auto_investigate: boolean;
  muted: boolean;
  mute_expires_at: string | null;
}

const API_BASE =
  process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:7600/api/v1";

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [muteModal, setMuteModal] = useState<{ ruleId: string; ruleName: string } | null>(null);
  const [muteDuration, setMuteDuration] = useState(24);

  const fetchAlerts = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (severityFilter !== "all") params.set("severity", severityFilter);
      const res = await fetch(`${API_BASE}/alerts?${params}`);
      const data = await res.json();
      setAlerts(data.alerts || []);
    } catch {
      // ignore
    }
  }, [statusFilter, severityFilter]);

  const fetchRules = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/rules`);
      const data = await res.json();
      setRules(data.rules || []);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    async function load() {
      await Promise.all([fetchAlerts(), fetchRules()]);
      setLoading(false);
    }
    load();
    const timer = setInterval(() => {
      fetchAlerts();
      fetchRules();
    }, 15000);
    return () => clearInterval(timer);
  }, [fetchAlerts, fetchRules]);

  const acknowledgeAlert = async (alertId: string) => {
    await fetch(`${API_BASE}/alerts/${alertId}/acknowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    fetchAlerts();
  };

  const resolveAlert = async (alertId: string) => {
    await fetch(`${API_BASE}/alerts/${alertId}/resolve`, {
      method: "POST",
    });
    fetchAlerts();
  };

  const muteRule = async (ruleId: string, hours: number) => {
    await fetch(`${API_BASE}/rules/${ruleId}/mute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration_hours: hours }),
    });
    setMuteModal(null);
    fetchRules();
  };

  const unmuteRule = async (ruleId: string) => {
    await fetch(`${API_BASE}/rules/${ruleId}/unmute`, {
      method: "POST",
    });
    fetchRules();
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--muted)]">
        Loading alerts...
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-auto p-4">
      {/* Alerts Section */}
      <div className="mb-8">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold">Alerts</h1>
          <div className="flex items-center gap-3">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-sm text-[var(--foreground)]"
            >
              <option value="all">All Status</option>
              <option value="active">Active</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
            </select>
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-sm text-[var(--foreground)]"
            >
              <option value="all">All Severity</option>
              <option value="NOTABLE">Notable</option>
              <option value="URGENT">Urgent</option>
            </select>
            <span className="text-sm text-[var(--muted)]">
              {alerts.length} alert{alerts.length !== 1 ? "s" : ""}
            </span>
          </div>
        </div>

        {alerts.length === 0 ? (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center text-[var(--muted)]">
            No alerts found
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-[var(--border)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--card)]">
                  <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Severity</th>
                  <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Message</th>
                  <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Source</th>
                  <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Time</th>
                  <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Status</th>
                  <th className="px-4 py-2 text-right font-medium text-[var(--muted)]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr
                    key={alert.id}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--card)]/50"
                  >
                    <td className="px-4 py-2">
                      <span
                        className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                          alert.severity === "URGENT"
                            ? "bg-red-900/30 text-red-400"
                            : "bg-yellow-900/30 text-yellow-400"
                        }`}
                      >
                        {alert.severity}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-[var(--foreground)]">
                      <div className="font-medium">{alert.rule_name}</div>
                      <div className="text-xs text-[var(--muted)] truncate max-w-md">
                        {alert.message}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-[var(--muted)]">{alert.source}</td>
                    <td className="px-4 py-2 text-[var(--muted)] whitespace-nowrap">
                      {new Date(alert.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                          alert.status === "active"
                            ? "bg-blue-900/30 text-blue-400"
                            : alert.status === "acknowledged"
                              ? "bg-purple-900/30 text-purple-400"
                              : "bg-green-900/30 text-green-400"
                        }`}
                      >
                        {alert.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {alert.status === "active" && (
                          <button
                            onClick={() => acknowledgeAlert(alert.id)}
                            className="rounded bg-purple-600/20 px-2 py-1 text-xs text-purple-400 hover:bg-purple-600/30"
                          >
                            Ack
                          </button>
                        )}
                        {alert.status !== "resolved" && (
                          <button
                            onClick={() => resolveAlert(alert.id)}
                            className="rounded bg-green-600/20 px-2 py-1 text-xs text-green-400 hover:bg-green-600/30"
                          >
                            Resolve
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Rules Section */}
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold">Alert Rules</h2>
          <span className="text-sm text-[var(--muted)]">
            {rules.length} rule{rules.length !== 1 ? "s" : ""}
          </span>
        </div>

        <div className="overflow-hidden rounded-lg border border-[var(--border)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--card)]">
                <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Rule</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Event Types</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Cooldown</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Auto-Investigate</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--muted)]">Status</th>
                <th className="px-4 py-2 text-right font-medium text-[var(--muted)]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr
                  key={rule.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--card)]/50"
                >
                  <td className="px-4 py-2 text-[var(--foreground)] font-medium">
                    {rule.name}
                  </td>
                  <td className="px-4 py-2 text-[var(--muted)]">
                    <div className="flex flex-wrap gap-1">
                      {rule.event_types.slice(0, 3).map((et) => (
                        <span
                          key={et}
                          className="inline-block rounded bg-[var(--card)] px-1.5 py-0.5 text-xs"
                        >
                          {et}
                        </span>
                      ))}
                      {rule.event_types.length > 3 && (
                        <span className="text-xs">+{rule.event_types.length - 3}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-[var(--muted)] whitespace-nowrap">
                    {rule.cooldown_seconds >= 3600
                      ? `${(rule.cooldown_seconds / 3600).toFixed(1)}h`
                      : `${Math.round(rule.cooldown_seconds / 60)}m`}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        rule.auto_investigate ? "bg-green-500" : "bg-gray-500"
                      }`}
                    />
                  </td>
                  <td className="px-4 py-2">
                    {rule.muted ? (
                      <span className="inline-block rounded bg-orange-900/30 px-2 py-0.5 text-xs text-orange-400">
                        Muted until{" "}
                        {rule.mute_expires_at
                          ? new Date(rule.mute_expires_at).toLocaleString()
                          : "—"}
                      </span>
                    ) : (
                      <span className="inline-block rounded bg-green-900/30 px-2 py-0.5 text-xs text-green-400">
                        Active
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {rule.muted ? (
                      <button
                        onClick={() => unmuteRule(rule.id)}
                        className="rounded bg-green-600/20 px-2 py-1 text-xs text-green-400 hover:bg-green-600/30"
                      >
                        Unmute
                      </button>
                    ) : (
                      <button
                        onClick={() =>
                          setMuteModal({ ruleId: rule.id, ruleName: rule.name })
                        }
                        className="rounded bg-orange-600/20 px-2 py-1 text-xs text-orange-400 hover:bg-orange-600/30"
                      >
                        Mute
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mute Duration Modal */}
      {muteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold">
              Mute &quot;{muteModal.ruleName}&quot;
            </h3>
            <div className="mb-4">
              <label className="mb-1 block text-sm text-[var(--muted)]">
                Duration (hours)
              </label>
              <select
                value={muteDuration}
                onChange={(e) => setMuteDuration(Number(e.target.value))}
                className="w-full rounded border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)]"
              >
                <option value={1}>1 hour</option>
                <option value={4}>4 hours</option>
                <option value={8}>8 hours</option>
                <option value={24}>24 hours</option>
                <option value={48}>48 hours</option>
                <option value={72}>72 hours</option>
                <option value={168}>7 days</option>
              </select>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setMuteModal(null)}
                className="rounded px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)]"
              >
                Cancel
              </button>
              <button
                onClick={() => muteRule(muteModal.ruleId, muteDuration)}
                className="rounded bg-orange-600 px-3 py-1.5 text-sm text-white hover:bg-orange-500"
              >
                Mute
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
