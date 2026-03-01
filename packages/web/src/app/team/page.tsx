"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

interface Member {
  id: string;
  user_id: string;
  username: string;
  email: string;
  role: string;
  joined_at: string | null;
}

interface Invitation {
  id: string;
  email: string;
  role: string;
  invited_by: string;
  expires_at: string | null;
  created_at: string | null;
}

const apiBase = process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

function UsageBar({ current, limit, label }: { current: number; limit: number; label: string }) {
  const pct = limit > 0 ? Math.min((current / limit) * 100, 100) : 0;
  return (
    <div className="text-xs text-[var(--muted)]">
      <span>{label}: {current} / {limit}</span>
      <div className="mt-1 h-1.5 w-full rounded bg-[var(--border)]">
        <div
          className="h-full rounded bg-argus-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function TeamPage() {
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteToken, setInviteToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [billingStatus, setBillingStatus] = useState<{ team_members?: { current: number; limit: number } } | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [membersRes, invitationsRes, billingRes] = await Promise.all([
        fetch(`${apiBase}/api/v1/team/members`, { credentials: "include" }),
        fetch(`${apiBase}/api/v1/team/invitations`, { credentials: "include" }),
        fetch(`${apiBase}/api/v1/billing/status`, { credentials: "include" }).catch(() => null),
      ]);
      if (membersRes.ok) setMembers(await membersRes.json());
      if (invitationsRes.ok) setInvitations(await invitationsRes.json());
      if (billingRes?.ok) setBillingStatus(await billingRes.json());
    } catch {
      setError("Failed to load team data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    setError("");
    setInviteToken("");
    try {
      const res = await fetch(`${apiBase}/api/v1/team/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to send invitation");
        return;
      }
      const data = await res.json();
      setInviteToken(data.token);
      setInviteEmail("");
      fetchData();
    } catch {
      setError("Failed to send invitation");
    }
  }

  async function handleRemove(userId: string) {
    if (!confirm("Remove this team member?")) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/team/members/${userId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to remove member");
        return;
      }
      fetchData();
    } catch {
      setError("Failed to remove member");
    }
  }

  async function handleRoleChange(userId: string, newRole: string) {
    try {
      const res = await fetch(`${apiBase}/api/v1/team/members/${userId}/role`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ role: newRole }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to update role");
        return;
      }
      fetchData();
    } catch {
      setError("Failed to update role");
    }
  }

  async function handleRevokeInvitation(invitationId: string) {
    try {
      const res = await fetch(`${apiBase}/api/v1/team/invitations/${invitationId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (res.ok) fetchData();
    } catch {
      setError("Failed to revoke invitation");
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-[var(--muted)]">
        Loading team...
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <h1 className="text-xl font-semibold">Team Management</h1>

      {billingStatus?.team_members && (
        <div className="w-64">
          <UsageBar
            current={billingStatus.team_members.current}
            limit={billingStatus.team_members.limit}
            label="Team members"
          />
        </div>
      )}

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Members table */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-sm font-medium">Members</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
              <th className="px-4 py-2">Username</th>
              <th className="px-4 py-2">Email</th>
              <th className="px-4 py-2">Role</th>
              <th className="px-4 py-2">Joined</th>
              <th className="px-4 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id} className="border-b border-[var(--border)] last:border-0">
                <td className="px-4 py-2">{m.username}</td>
                <td className="px-4 py-2 text-[var(--muted)]">{m.email}</td>
                <td className="px-4 py-2">
                  {m.role === "owner" ? (
                    <span className="rounded bg-argus-600/20 px-2 py-0.5 text-xs text-argus-400">
                      owner
                    </span>
                  ) : (
                    <select
                      value={m.role}
                      onChange={(e) => handleRoleChange(m.user_id, e.target.value)}
                      className="rounded border border-[var(--border)] bg-transparent px-1 py-0.5 text-xs"
                    >
                      <option value="member">member</option>
                      <option value="admin">admin</option>
                    </select>
                  )}
                </td>
                <td className="px-4 py-2 text-[var(--muted)]">
                  {m.joined_at ? new Date(m.joined_at).toLocaleDateString() : "-"}
                </td>
                <td className="px-4 py-2">
                  {m.role !== "owner" && (
                    <button
                      onClick={() => handleRemove(m.user_id)}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Invite form */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 text-sm font-medium">Invite Member</h2>
        <form onSubmit={handleInvite} className="flex items-end gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-[var(--muted)]">Email</label>
            <input
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm focus:border-argus-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[var(--muted)]">Role</label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            >
              <option value="member">member</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <button
            type="submit"
            className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500"
          >
            Send Invite
          </button>
        </form>

        {inviteToken && (
          <div className="mt-3 rounded border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm">
            <p className="mb-1 text-emerald-400">Invitation created! Share this token:</p>
            <code className="block break-all rounded bg-[var(--background)] px-2 py-1 text-xs">
              {inviteToken}
            </code>
          </div>
        )}
      </div>

      {/* Pending invitations */}
      {invitations.length > 0 && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <div className="border-b border-[var(--border)] px-4 py-3">
            <h2 className="text-sm font-medium">Pending Invitations</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
                <th className="px-4 py-2">Email</th>
                <th className="px-4 py-2">Role</th>
                <th className="px-4 py-2">Expires</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {invitations.map((inv) => (
                <tr key={inv.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2">{inv.email}</td>
                  <td className="px-4 py-2">{inv.role}</td>
                  <td className="px-4 py-2 text-[var(--muted)]">
                    {inv.expires_at ? new Date(inv.expires_at).toLocaleDateString() : "-"}
                  </td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => handleRevokeInvitation(inv.id)}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
