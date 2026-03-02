"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useDeployment } from "@/hooks/useDeployment";

interface Investigation {
  id: string;
  trigger: string;
  summary: string;
  tokens_used: number;
  conversation_id: string;
  alert_id: number;
  assigned_to: string;
  assigned_by: string;
  service_name: string;
  created_at: string | null;
  completed_at: string | null;
}

interface TeamMember {
  user_id: string;
  username: string;
  role: string;
}

const API_BASE =
  process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

export default function InvestigationsPage() {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterAssigned, setFilterAssigned] = useState("");
  const [filterService, setFilterService] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const { isSaaS } = useDeployment();

  const fetchInvestigations = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page: String(page) });
      if (filterAssigned) params.set("assigned_to", filterAssigned);
      if (filterService) params.set("service", filterService);

      const res = await apiFetch(
        `${API_BASE}/api/v1/investigations?${params}`
      );
      const data = await res.json();
      setInvestigations(data.investigations || []);
      setTotalPages(data.total_pages || 1);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, filterAssigned, filterService]);

  useEffect(() => {
    fetchInvestigations();
    const timer = setInterval(fetchInvestigations, 15000);
    return () => clearInterval(timer);
  }, [fetchInvestigations]);

  useEffect(() => {
    if (!isSaaS) return;
    apiFetch(`${API_BASE}/api/v1/team/members`)
      .then((r) => r.json())
      .then((d) => setTeamMembers(d.members || []))
      .catch(() => {});
  }, [isSaaS]);

  function getMemberName(userId: string) {
    if (!userId) return "";
    const m = teamMembers.find((t) => t.user_id === userId);
    return m?.username || userId.slice(0, 8);
  }

  async function handleAssign(investigationId: string, assignedTo: string) {
    if (assignedTo) {
      await apiFetch(
        `${API_BASE}/api/v1/investigations/${investigationId}/assign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ assigned_to: assignedTo }),
        }
      );
    } else {
      await apiFetch(
        `${API_BASE}/api/v1/investigations/${investigationId}/unassign`,
        { method: "POST" }
      );
    }
    fetchInvestigations();
  }

  // Collect unique services for filter
  const services = [
    ...new Set(investigations.map((i) => i.service_name).filter(Boolean)),
  ];

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--muted)]">
        Loading investigations...
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-auto p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Investigations</h1>
        {isSaaS && (
          <div className="flex items-center gap-2 text-xs">
            <select
              value={filterAssigned}
              onChange={(e) => {
                setFilterAssigned(e.target.value);
                setPage(1);
              }}
              className="rounded border border-[var(--border)] bg-transparent px-2 py-1"
            >
              <option value="">All assignees</option>
              {teamMembers.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.username}
                </option>
              ))}
            </select>
            {services.length > 0 && (
              <select
                value={filterService}
                onChange={(e) => {
                  setFilterService(e.target.value);
                  setPage(1);
                }}
                className="rounded border border-[var(--border)] bg-transparent px-2 py-1"
              >
                <option value="">All services</option>
                {services.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
      </div>

      {investigations.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center text-center text-[var(--muted)]">
          <p className="mb-2 text-lg">No investigations yet</p>
          <p className="text-sm">
            Investigations are created automatically when the AI agent detects
            issues.
          </p>
        </div>
      ) : (
        <>
          <div className="overflow-auto rounded-lg border border-[var(--border)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--card)]">
                  <th className="px-3 py-2 text-left font-medium">Trigger</th>
                  <th className="px-3 py-2 text-left font-medium">Summary</th>
                  {isSaaS && (
                    <>
                      <th className="px-3 py-2 text-left font-medium">
                        Service
                      </th>
                      <th className="px-3 py-2 text-left font-medium">
                        Assigned
                      </th>
                    </>
                  )}
                  <th className="px-3 py-2 text-left font-medium">Tokens</th>
                  <th className="px-3 py-2 text-left font-medium">Created</th>
                  <th className="px-3 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {investigations.map((inv) => (
                  <tr
                    key={inv.id}
                    className="border-b border-[var(--border)] hover:bg-[var(--card)]"
                  >
                    <td className="max-w-[200px] truncate px-3 py-2">
                      {inv.trigger || "-"}
                    </td>
                    <td className="max-w-[300px] truncate px-3 py-2 text-[var(--muted)]">
                      {inv.summary || "-"}
                    </td>
                    {isSaaS && (
                      <>
                        <td className="px-3 py-2 text-xs">
                          {inv.service_name || "-"}
                        </td>
                        <td className="px-3 py-2">
                          <select
                            value={inv.assigned_to}
                            onChange={(e) =>
                              handleAssign(inv.id, e.target.value)
                            }
                            className="rounded border border-[var(--border)] bg-transparent px-1 py-0.5 text-xs"
                          >
                            <option value="">Unassigned</option>
                            {teamMembers.map((m) => (
                              <option key={m.user_id} value={m.user_id}>
                                {m.username}
                              </option>
                            ))}
                          </select>
                        </td>
                      </>
                    )}
                    <td className="px-3 py-2 text-xs text-[var(--muted)]">
                      {inv.tokens_used.toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--muted)]">
                      {inv.created_at
                        ? new Date(inv.created_at).toLocaleString()
                        : "-"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          inv.completed_at
                            ? "bg-green-900/20 text-green-400"
                            : "bg-yellow-900/20 text-yellow-400"
                        }`}
                      >
                        {inv.completed_at ? "Completed" : "In Progress"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-center gap-2 text-sm">
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="rounded border border-[var(--border)] px-3 py-1 disabled:opacity-40"
              >
                Previous
              </button>
              <span className="text-[var(--muted)]">
                Page {page} of {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                className="rounded border border-[var(--border)] px-3 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
