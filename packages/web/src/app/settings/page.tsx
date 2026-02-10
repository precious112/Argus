"use client";

import { useEffect, useState } from "react";

interface Settings {
  llm: { provider: string; model: string; status: string };
  budget: Record<string, number>;
  collectors: { metrics_interval: number; process_interval: number; log_paths: string[] };
  alerting: { webhook_count: number; email_enabled: boolean };
  server: { host: string; port: number };
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const url =
      process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:7600/api/v1";
    fetch(`${url}/settings`)
      .then((r) => r.json())
      .then(setSettings)
      .catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <h2 className="mb-6 text-xl font-semibold">Settings</h2>
        <p className="text-red-400">Failed to load settings: {error}</p>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <h2 className="mb-6 text-xl font-semibold">Settings</h2>
        <p className="text-[var(--muted)]">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h2 className="mb-6 text-xl font-semibold">Settings</h2>
      <p className="mb-6 text-sm text-[var(--muted)]">
        Read-only view. Configuration changes require environment variable or
        YAML file updates and a server restart.
      </p>

      {/* LLM Provider */}
      <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h3 className="mb-3 text-lg font-medium">LLM Provider</h3>
        <div className="space-y-2 text-sm">
          <Row label="Provider" value={settings.llm.provider} />
          <Row label="Model" value={settings.llm.model} />
          <Row label="Status" value={settings.llm.status} />
        </div>
      </section>

      {/* Budget */}
      {settings.budget && Object.keys(settings.budget).length > 0 && (
        <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h3 className="mb-3 text-lg font-medium">AI Budget</h3>
          <div className="space-y-2 text-sm">
            <Row
              label="Hourly"
              value={`${settings.budget.hourly_used || 0} / ${settings.budget.hourly_limit || 0} tokens`}
            />
            <Row
              label="Daily"
              value={`${settings.budget.daily_used || 0} / ${settings.budget.daily_limit || 0} tokens`}
            />
          </div>
        </section>
      )}

      {/* Collectors */}
      <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h3 className="mb-3 text-lg font-medium">Collectors</h3>
        <div className="space-y-2 text-sm">
          <Row
            label="Metrics Interval"
            value={`${settings.collectors.metrics_interval}s`}
          />
          <Row
            label="Process Interval"
            value={`${settings.collectors.process_interval}s`}
          />
          <Row
            label="Log Paths"
            value={settings.collectors.log_paths.join(", ")}
          />
        </div>
      </section>

      {/* Alerting */}
      <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h3 className="mb-3 text-lg font-medium">Alerting</h3>
        <div className="space-y-2 text-sm">
          <Row
            label="Webhooks"
            value={`${settings.alerting.webhook_count} configured`}
          />
          <Row
            label="Email"
            value={settings.alerting.email_enabled ? "Enabled" : "Disabled"}
          />
        </div>
      </section>

      {/* Server */}
      <section className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
        <h3 className="mb-3 text-lg font-medium">Server</h3>
        <div className="space-y-2 text-sm">
          <Row label="Host" value={settings.server.host} />
          <Row label="Port" value={String(settings.server.port)} />
        </div>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-[var(--muted)]">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
