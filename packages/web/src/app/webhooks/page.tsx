"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDeployment } from "@/hooks/useDeployment";

interface WebhookInfo {
  id: string;
  name: string;
  url: string;
  events: string;
  mode: string;
  remote_tools: string;
  timeout_seconds: number;
  is_active: boolean;
  last_ping_at: string | null;
  last_ping_status: string;
  created_at: string | null;
  updated_at: string | null;
  secret?: string;
}

const apiBase = process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

const MODE_LABELS: Record<string, string> = {
  alerts_only: "Alerts Only",
  tool_execution: "Tool Execution",
  both: "Both",
};

function StatusDot({ status }: { status: string }) {
  const color =
    status === "ok"
      ? "bg-emerald-400"
      : status === "error" || status === "timeout"
        ? "bg-red-400"
        : "bg-gray-500";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export default function WebhooksPage() {
  const { isSaaS } = useDeployment();
  const [webhooks, setWebhooks] = useState<WebhookInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [createdSecret, setCreatedSecret] = useState("");
  const [copied, setCopied] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);

  // Create form state
  const [formName, setFormName] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [formMode, setFormMode] = useState("tool_execution");
  const [formTools, setFormTools] = useState("*");
  const [formTimeout, setFormTimeout] = useState(30);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/api/v1/webhooks/config`, {
        credentials: "include",
      });
      if (res.ok) setWebhooks(await res.json());
      else setError("Failed to load webhooks");
    } catch {
      setError("Failed to load webhooks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    setCreatedSecret("");
    try {
      const res = await fetch(`${apiBase}/api/v1/webhooks/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: formName,
          url: formUrl,
          mode: formMode,
          remote_tools: formTools,
          timeout_seconds: formTimeout,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to create webhook");
        return;
      }
      const data = await res.json();
      setCreatedSecret(data.secret || "");
      setFormName("");
      setFormUrl("");
      setFormMode("tool_execution");
      setFormTools("*");
      setFormTimeout(30);
      setShowCreate(false);
      fetchData();
    } catch {
      setError("Failed to create webhook");
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this webhook? This cannot be undone.")) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/webhooks/config/${id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to delete webhook");
        return;
      }
      fetchData();
    } catch {
      setError("Failed to delete webhook");
    }
  }

  async function handleToggle(wh: WebhookInfo) {
    try {
      await fetch(`${apiBase}/api/v1/webhooks/config/${wh.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ is_active: !wh.is_active }),
      });
      fetchData();
    } catch {
      setError("Failed to update webhook");
    }
  }

  async function handleTest(id: string) {
    setTestingId(id);
    try {
      const res = await fetch(
        `${apiBase}/api/v1/webhooks/config/${id}/test`,
        { method: "POST", credentials: "include" }
      );
      const data = await res.json();
      if (data.success) {
        setError("");
      } else {
        setError(`Test failed: ${data.status}`);
      }
      fetchData();
    } catch {
      setError("Test request failed");
    } finally {
      setTestingId(null);
    }
  }

  function handleCopySecret() {
    navigator.clipboard.writeText(createdSecret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!isSaaS) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-[var(--muted)]">
        Webhooks are only available in SaaS mode.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-[var(--muted)]">
        Loading webhooks...
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Webhooks</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500"
        >
          {showCreate ? "Cancel" : "Add Webhook"}
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {createdSecret && (
        <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm">
          <p className="mb-1 text-emerald-400">
            Webhook created! Copy the secret now — it won&apos;t be shown
            again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-[var(--background)] px-2 py-1 text-xs">
              {createdSecret}
            </code>
            <button
              onClick={handleCopySecret}
              className="rounded border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--card)]"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h2 className="mb-3 text-sm font-medium">New Webhook</h2>
          <form onSubmit={handleCreate} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs text-[var(--muted)]">
                  Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Production Server"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm focus:border-argus-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--muted)]">
                  URL
                </label>
                <input
                  type="url"
                  required
                  placeholder="https://your-server.com/argus/webhook"
                  value={formUrl}
                  onChange={(e) => setFormUrl(e.target.value)}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm focus:border-argus-500 focus:outline-none"
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="mb-1 block text-xs text-[var(--muted)]">
                  Mode
                </label>
                <select
                  value={formMode}
                  onChange={(e) => setFormMode(e.target.value)}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
                >
                  <option value="alerts_only">Alerts Only</option>
                  <option value="tool_execution">Tool Execution</option>
                  <option value="both">Both</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--muted)]">
                  Remote Tools
                </label>
                <input
                  type="text"
                  placeholder="* (all) or comma-separated"
                  value={formTools}
                  onChange={(e) => setFormTools(e.target.value)}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm focus:border-argus-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--muted)]">
                  Timeout (s)
                </label>
                <input
                  type="number"
                  min={5}
                  max={120}
                  value={formTimeout}
                  onChange={(e) => setFormTimeout(Number(e.target.value))}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm focus:border-argus-500 focus:outline-none"
                />
              </div>
            </div>
            <button
              type="submit"
              className="rounded bg-argus-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-argus-500"
            >
              Create Webhook
            </button>
          </form>
        </div>
      )}

      {/* Webhooks table */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-sm font-medium">Configured Webhooks</h2>
        </div>
        {webhooks.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-[var(--muted)]">
            No webhooks configured. Add one above to enable remote tool
            execution.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">URL</th>
                <th className="px-4 py-2">Mode</th>
                <th className="px-4 py-2">Last Ping</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {webhooks.map((wh) => (
                <tr
                  key={wh.id}
                  className="border-b border-[var(--border)] last:border-0"
                >
                  <td className="px-4 py-2">
                    <StatusDot
                      status={wh.is_active ? wh.last_ping_status || "unknown" : "disabled"}
                    />
                  </td>
                  <td className="px-4 py-2">{wh.name || "-"}</td>
                  <td className="max-w-[200px] truncate px-4 py-2 text-[var(--muted)]">
                    {wh.url}
                  </td>
                  <td className="px-4 py-2 text-[var(--muted)]">
                    {MODE_LABELS[wh.mode] || wh.mode}
                  </td>
                  <td className="px-4 py-2 text-[var(--muted)]">
                    {wh.last_ping_at
                      ? new Date(wh.last_ping_at).toLocaleString()
                      : "Never"}
                  </td>
                  <td className="flex items-center gap-2 px-4 py-2">
                    <button
                      onClick={() => handleTest(wh.id)}
                      disabled={testingId === wh.id}
                      className="text-xs text-argus-400 hover:text-argus-300 disabled:opacity-50"
                    >
                      {testingId === wh.id ? "Testing..." : "Test"}
                    </button>
                    <button
                      onClick={() => handleToggle(wh)}
                      className="text-xs text-yellow-400 hover:text-yellow-300"
                    >
                      {wh.is_active ? "Disable" : "Enable"}
                    </button>
                    <button
                      onClick={() => handleDelete(wh.id)}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* SDK Setup Instructions */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 text-sm font-medium">SDK Setup</h2>
        <p className="mb-3 text-xs text-[var(--muted)]">
          Install the Argus SDK on your server and start the webhook handler to
          receive tool execution requests from the Argus AI agent.
        </p>

        <div className="space-y-4">
          <div>
            <h3 className="mb-1 text-xs font-medium text-[var(--muted)]">
              Python (FastAPI)
            </h3>
            <pre className="overflow-x-auto rounded bg-[var(--background)] p-3 text-xs">
              <code>{`from argus.webhook import ArgusWebhookHandler
from fastapi import FastAPI

app = FastAPI()
handler = ArgusWebhookHandler(webhook_secret="YOUR_SECRET")
app.include_router(handler.fastapi_router())`}</code>
            </pre>
          </div>

          <div>
            <h3 className="mb-1 text-xs font-medium text-[var(--muted)]">
              Python (Flask)
            </h3>
            <pre className="overflow-x-auto rounded bg-[var(--background)] p-3 text-xs">
              <code>{`from argus.webhook import ArgusWebhookHandler
from flask import Flask

app = Flask(__name__)
handler = ArgusWebhookHandler(webhook_secret="YOUR_SECRET")
app.register_blueprint(handler.flask_blueprint())`}</code>
            </pre>
          </div>

          <div>
            <h3 className="mb-1 text-xs font-medium text-[var(--muted)]">
              Node.js (Express)
            </h3>
            <pre className="overflow-x-auto rounded bg-[var(--background)] p-3 text-xs">
              <code>{`import { ArgusWebhookHandler } from '@argus/sdk-node';
import express from 'express';

const app = express();
const handler = new ArgusWebhookHandler({
  webhookSecret: 'YOUR_SECRET',
});
app.use(handler.expressMiddleware());`}</code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
