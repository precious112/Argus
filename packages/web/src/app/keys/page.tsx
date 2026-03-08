"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

interface ApiKeyInfo {
  id: string;
  name: string;
  key_prefix: string;
  environment: string;
  last_used_at: string | null;
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

export default function KeysPage() {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyEnv, setNewKeyEnv] = useState("production");
  const [createdKey, setCreatedKey] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [billingStatus, setBillingStatus] = useState<{ api_keys?: { current: number; limit: number } } | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [keysRes, billingRes] = await Promise.all([
        fetch(`${apiBase}/api/v1/keys`, { credentials: "include" }),
        fetch(`${apiBase}/api/v1/billing/status`, { credentials: "include" }).catch(() => null),
      ]);
      if (keysRes.ok) setKeys(await keysRes.json());
      if (billingRes?.ok) setBillingStatus(await billingRes.json());
    } catch {
      setError("Failed to load API keys");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    setCreatedKey("");
    setCopied(false);
    try {
      const res = await fetch(`${apiBase}/api/v1/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: newKeyName, environment: newKeyEnv }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to create key");
        return;
      }
      const data = await res.json();
      setCreatedKey(data.plain_key || data.key || "");
      setNewKeyName("");
      fetchData();
    } catch {
      setError("Failed to create key");
    }
  }

  async function handleRevoke(keyId: string) {
    if (!confirm("Revoke this API key? This cannot be undone.")) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/keys/${keyId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to revoke key");
        return;
      }
      fetchData();
    } catch {
      setError("Failed to revoke key");
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(createdKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-[var(--muted)]">
        Loading API keys...
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <h1 className="text-xl font-semibold">API Keys</h1>

      {billingStatus?.api_keys && (
        <div className="w-64">
          <UsageBar
            current={billingStatus.api_keys.current}
            limit={billingStatus.api_keys.limit}
            label="API keys"
          />
        </div>
      )}

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Create key form */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 text-sm font-medium">Create New Key</h2>
        <form onSubmit={handleCreate} className="flex items-end gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-[var(--muted)]">Name</label>
            <input
              type="text"
              placeholder="e.g. Production Backend"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm focus:border-argus-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[var(--muted)]">Environment</label>
            <select
              value={newKeyEnv}
              onChange={(e) => setNewKeyEnv(e.target.value)}
              className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            >
              <option value="production">production</option>
              <option value="staging">staging</option>
              <option value="development">development</option>
            </select>
          </div>
          <button
            type="submit"
            className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500"
          >
            Create Key
          </button>
        </form>

        {createdKey && (
          <div className="mt-3 rounded border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm">
            <p className="mb-1 text-emerald-400">
              API key created! Copy it now — it won&apos;t be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all rounded bg-[var(--background)] px-2 py-1 text-xs">
                {createdKey}
              </code>
              <button
                onClick={handleCopy}
                className="rounded border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--card)]"
              >
                {copied ? "Copied!" : "Copy"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Keys table */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-sm font-medium">Active Keys</h2>
        </div>
        {keys.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-[var(--muted)]">
            No API keys yet. Create one above.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Key Prefix</th>
                <th className="px-4 py-2">Environment</th>
                <th className="px-4 py-2">Last Used</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2">{k.name || "-"}</td>
                  <td className="px-4 py-2">
                    <code className="rounded bg-[var(--background)] px-1.5 py-0.5 text-xs">
                      {k.key_prefix}...
                    </code>
                  </td>
                  <td className="px-4 py-2 text-[var(--muted)]">{k.environment}</td>
                  <td className="px-4 py-2 text-[var(--muted)]">
                    {k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : "Never"}
                  </td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => handleRevoke(k.id)}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
