"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface EscalationPolicy {
  id: string;
  name: string;
  service_name: string;
  min_severity: string;
  primary_contact_id: string;
  backup_contact_id: string;
  is_active: boolean;
}

interface TeamMember {
  user_id: string;
  username: string;
  role: string;
}

const API_BASE =
  process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

export default function EscalationPage() {
  const [policies, setPolicies] = useState<EscalationPolicy[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    service_name: "",
    min_severity: "",
    primary_contact_id: "",
    backup_contact_id: "",
  });
  const [saving, setSaving] = useState(false);

  const fetchPolicies = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/v1/escalation-policies`);
      const data = await res.json();
      setPolicies(data.policies || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPolicies();
    apiFetch(`${API_BASE}/api/v1/team/members`)
      .then((r) => r.json())
      .then((d) => setTeamMembers(d.members || []))
      .catch(() => {});
  }, [fetchPolicies]);

  function getMemberName(userId: string) {
    if (!userId) return "None";
    const m = teamMembers.find((t) => t.user_id === userId);
    return m?.username || userId.slice(0, 8);
  }

  function handleEdit(policy: EscalationPolicy) {
    setEditId(policy.id);
    setForm({
      name: policy.name,
      service_name: policy.service_name,
      min_severity: policy.min_severity,
      primary_contact_id: policy.primary_contact_id,
      backup_contact_id: policy.backup_contact_id,
    });
    setShowForm(true);
  }

  function handleNew() {
    setEditId(null);
    setForm({
      name: "",
      service_name: "",
      min_severity: "",
      primary_contact_id: "",
      backup_contact_id: "",
    });
    setShowForm(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      const url = editId
        ? `${API_BASE}/api/v1/escalation-policies/${editId}`
        : `${API_BASE}/api/v1/escalation-policies`;
      await apiFetch(url, {
        method: editId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      setShowForm(false);
      fetchPolicies();
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    await apiFetch(`${API_BASE}/api/v1/escalation-policies/${id}`, {
      method: "DELETE",
    });
    fetchPolicies();
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--muted)]">
        Loading...
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Escalation Policies</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Define who gets contacted when the AI needs human help.
          </p>
        </div>
        <button
          onClick={handleNew}
          className="rounded bg-argus-600 px-4 py-2 text-sm font-medium text-white hover:bg-argus-500"
        >
          Add Policy
        </button>
      </div>

      {showForm && (
        <div className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h3 className="mb-3 font-medium">
            {editId ? "Edit Policy" : "New Policy"}
          </h3>
          <div className="space-y-3 text-sm">
            <div>
              <label className="mb-1 block text-[var(--muted)]">Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5"
                placeholder="e.g., Critical Production Alerts"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-[var(--muted)]">
                  Service (optional)
                </label>
                <input
                  value={form.service_name}
                  onChange={(e) =>
                    setForm({ ...form, service_name: e.target.value })
                  }
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5"
                  placeholder="Leave empty for all"
                />
              </div>
              <div>
                <label className="mb-1 block text-[var(--muted)]">
                  Min Severity
                </label>
                <select
                  value={form.min_severity}
                  onChange={(e) =>
                    setForm({ ...form, min_severity: e.target.value })
                  }
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5"
                >
                  <option value="">Any</option>
                  <option value="NOTABLE">Notable</option>
                  <option value="URGENT">Urgent</option>
                  <option value="CRITICAL">Critical</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-[var(--muted)]">
                  Primary Contact
                </label>
                <select
                  value={form.primary_contact_id}
                  onChange={(e) =>
                    setForm({ ...form, primary_contact_id: e.target.value })
                  }
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5"
                >
                  <option value="">None</option>
                  {teamMembers.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.username}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[var(--muted)]">
                  Backup Contact
                </label>
                <select
                  value={form.backup_contact_id}
                  onChange={(e) =>
                    setForm({ ...form, backup_contact_id: e.target.value })
                  }
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5"
                >
                  <option value="">None</option>
                  {teamMembers.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.username}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <button
                onClick={handleSave}
                disabled={saving || !form.name}
                className="rounded bg-argus-600 px-4 py-1.5 text-sm text-white hover:bg-argus-500 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save"}
              </button>
              <button
                onClick={() => setShowForm(false)}
                className="rounded border border-[var(--border)] px-4 py-1.5 text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {policies.length === 0 && !showForm ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center text-[var(--muted)]">
          <p className="mb-2">No escalation policies configured</p>
          <p className="text-sm">
            Create a policy to define who gets contacted for alerts.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {policies.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"
            >
              <div>
                <h3 className="font-medium">{p.name}</h3>
                <div className="mt-1 flex gap-4 text-xs text-[var(--muted)]">
                  <span>
                    Service: {p.service_name || "All"}
                  </span>
                  <span>
                    Severity: {p.min_severity || "Any"}+
                  </span>
                  <span>
                    Primary: {getMemberName(p.primary_contact_id)}
                  </span>
                  <span>
                    Backup: {getMemberName(p.backup_contact_id)}
                  </span>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleEdit(p)}
                  className="rounded border border-[var(--border)] px-3 py-1 text-xs hover:bg-[var(--border)]"
                >
                  Edit
                </button>
                <button
                  onClick={() => handleDelete(p.id)}
                  className="rounded border border-red-800 px-3 py-1 text-xs text-red-400 hover:bg-red-900/20"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
