"use client";

import { useCallback, useEffect, useState } from "react";

const API =
  process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:7600/api/v1";

interface Settings {
  llm: {
    provider: string;
    model: string;
    status: string;
    api_key_set?: boolean;
    providers?: string[];
  };
  budget: Record<string, number>;
  collectors: {
    metrics_interval: number;
    process_interval: number;
    log_paths: string[];
  };
  alerting: { webhook_count: number; email_enabled: boolean };
  server: { host: string; port: number };
  notifications?: ChannelConfig[];
}

interface ChannelConfig {
  id: string;
  channel_type: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

/* ------------------------------------------------------------------ */
/*  Toggle                                                             */
/* ------------------------------------------------------------------ */
function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${checked ? "bg-[var(--accent)]" : "bg-[var(--border)]"}`}
    >
      <span
        className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0"}`}
      />
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  LLM Config Section                                                 */
/* ------------------------------------------------------------------ */
function LLMSection({
  initial,
  onSaved,
}: {
  initial: Settings["llm"];
  onSaved: () => void;
}) {
  const [provider, setProvider] = useState(initial.provider);
  const [model, setModel] = useState(initial.model);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);
  const [dirty, setDirty] = useState(false);

  const providers = initial.providers ?? ["openai", "anthropic", "gemini"];

  useEffect(() => {
    setDirty(true);
  }, [provider, model, apiKey]);

  const save = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const r = await fetch(`${API}/settings/llm`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model, api_key: apiKey || "••••••••" }),
      });
      if (!r.ok) throw new Error(await r.text());
      setFeedback({ ok: true, msg: "Saved" });
      setDirty(false);
      setApiKey("");
      onSaved();
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
      <h3 className="mb-3 text-lg font-medium">LLM Provider</h3>
      <div className="space-y-3 text-sm">
        <div>
          <label className="mb-1 block text-[var(--muted)]">Provider</label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
          >
            {providers.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-[var(--muted)]">Model</label>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 font-mono text-sm"
            placeholder="gpt-4o"
          />
        </div>
        <div>
          <label className="mb-1 block text-[var(--muted)]">API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 font-mono text-sm"
            placeholder={initial.api_key_set ? "Configured (leave blank to keep)" : "Not set"}
          />
        </div>
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-2">
            <button
              onClick={save}
              disabled={saving || !dirty}
              className="rounded bg-[var(--accent)] px-4 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-40"
            >
              {saving ? "Saving..." : "Save"}
            </button>
            {feedback && (
              <span
                className={`text-sm ${feedback.ok ? "text-green-400" : "text-red-400"}`}
              >
                {feedback.msg}
              </span>
            )}
          </div>
          <span className="text-xs text-[var(--muted)]">
            Status: {initial.status}
          </span>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Budget Config Section                                              */
/* ------------------------------------------------------------------ */
function BudgetSection({
  initial,
  onSaved,
}: {
  initial: Record<string, number>;
  onSaved: () => void;
}) {
  const [dailyLimit, setDailyLimit] = useState(initial.daily_limit || 500000);
  const [hourlyLimit, setHourlyLimit] = useState(
    initial.hourly_limit || 100000
  );
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setDirty(true);
  }, [dailyLimit, hourlyLimit]);

  const save = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const r = await fetch(`${API}/settings/budget`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          daily_token_limit: dailyLimit,
          hourly_token_limit: hourlyLimit,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      setFeedback({ ok: true, msg: "Saved" });
      setDirty(false);
      onSaved();
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  };

  const hourlyPct = initial.hourly_limit
    ? Math.min(
        100,
        Math.round(((initial.hourly_used || 0) / initial.hourly_limit) * 100)
      )
    : 0;
  const dailyPct = initial.daily_limit
    ? Math.min(
        100,
        Math.round(((initial.daily_used || 0) / initial.daily_limit) * 100)
      )
    : 0;

  return (
    <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
      <h3 className="mb-3 text-lg font-medium">AI Budget</h3>
      <div className="space-y-3 text-sm">
        <div>
          <label className="mb-1 block text-[var(--muted)]">
            Hourly Token Limit
          </label>
          <input
            type="number"
            value={hourlyLimit}
            onChange={(e) => setHourlyLimit(Number(e.target.value))}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
          />
          <div className="mt-1 flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-[var(--border)]">
              <div
                className="h-1.5 rounded-full bg-argus-500"
                style={{ width: `${hourlyPct}%` }}
              />
            </div>
            <span className="text-xs text-[var(--muted)]">
              {initial.hourly_used || 0} / {initial.hourly_limit || 0}
            </span>
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[var(--muted)]">
            Daily Token Limit
          </label>
          <input
            type="number"
            value={dailyLimit}
            onChange={(e) => setDailyLimit(Number(e.target.value))}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
          />
          <div className="mt-1 flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-[var(--border)]">
              <div
                className="h-1.5 rounded-full bg-argus-500"
                style={{ width: `${dailyPct}%` }}
              />
            </div>
            <span className="text-xs text-[var(--muted)]">
              {initial.daily_used || 0} / {initial.daily_limit || 0}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="rounded bg-[var(--accent)] px-4 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          {feedback && (
            <span
              className={`text-sm ${feedback.ok ? "text-green-400" : "text-red-400"}`}
            >
              {feedback.msg}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Slack Config Section                                               */
/* ------------------------------------------------------------------ */
function SlackSection({
  initial,
  onSaved,
}: {
  initial?: ChannelConfig;
  onSaved: () => void;
}) {
  const [enabled, setEnabled] = useState(initial?.enabled ?? false);
  const [botToken, setBotToken] = useState(
    (initial?.config?.bot_token as string) ?? ""
  );
  const [channelId, setChannelId] = useState(
    (initial?.config?.channel_id as string) ?? ""
  );
  const [channelName, setChannelName] = useState(
    (initial?.config?.channel_name as string) ?? ""
  );
  const [channels, setChannels] = useState<{ id: string; name: string }[]>([]);
  const [loadingChannels, setLoadingChannels] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setDirty(true);
  }, [enabled, botToken, channelId]);

  const loadChannels = async () => {
    setLoadingChannels(true);
    setFeedback(null);
    try {
      // Save token first so backend can use it
      await fetch(`${API}/notifications/settings/slack`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled,
          config: {
            bot_token: botToken,
            channel_id: channelId,
            channel_name: channelName,
          },
        }),
      });
      const r = await fetch(`${API}/notifications/slack/channels`);
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setChannels(data.channels ?? []);
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Failed to load channels",
      });
    } finally {
      setLoadingChannels(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const r = await fetch(`${API}/notifications/settings/slack`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled,
          config: {
            bot_token: botToken,
            channel_id: channelId,
            channel_name: channelName,
          },
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      setFeedback({ ok: true, msg: "Saved" });
      setDirty(false);
      onSaved();
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setFeedback(null);
    try {
      const r = await fetch(`${API}/notifications/test/slack`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(await r.text());
      setFeedback({ ok: true, msg: "Test message sent!" });
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Test failed",
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-lg font-medium">Slack</h3>
        <Toggle checked={enabled} onChange={setEnabled} />
      </div>
      <div className="space-y-3 text-sm">
        <div>
          <label className="mb-1 block text-[var(--muted)]">Bot Token</label>
          <input
            type="password"
            value={botToken}
            onChange={(e) => setBotToken(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 font-mono text-sm"
            placeholder="xoxb-..."
          />
        </div>
        <div>
          <label className="mb-1 block text-[var(--muted)]">Channel</label>
          <div className="flex gap-2">
            {channels.length > 0 ? (
              <select
                value={channelId}
                onChange={(e) => {
                  setChannelId(e.target.value);
                  const ch = channels.find((c) => c.id === e.target.value);
                  if (ch) setChannelName(ch.name);
                }}
                className="flex-1 rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
              >
                <option value="">Select a channel</option>
                {channels.map((ch) => (
                  <option key={ch.id} value={ch.id}>
                    #{ch.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={channelId}
                onChange={(e) => setChannelId(e.target.value)}
                className="flex-1 rounded border border-[var(--border)] bg-transparent px-3 py-1.5 font-mono text-sm"
                placeholder="C0123456789"
              />
            )}
            <button
              onClick={loadChannels}
              disabled={!botToken || loadingChannels}
              className="rounded bg-[var(--border)] px-3 py-1.5 text-sm hover:opacity-80 disabled:opacity-40"
            >
              {loadingChannels ? "Loading..." : "Load Channels"}
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="rounded bg-[var(--accent)] px-4 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <button
            onClick={test}
            disabled={testing || !channelId}
            className="rounded border border-[var(--border)] px-4 py-1.5 text-sm hover:opacity-80 disabled:opacity-40"
          >
            {testing ? "Testing..." : "Test"}
          </button>
          {feedback && (
            <span
              className={`text-sm ${feedback.ok ? "text-green-400" : "text-red-400"}`}
            >
              {feedback.msg}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Email Config Section                                               */
/* ------------------------------------------------------------------ */
function EmailSection({
  initial,
  onSaved,
}: {
  initial?: ChannelConfig;
  onSaved: () => void;
}) {
  const cfg = initial?.config ?? {};
  const [enabled, setEnabled] = useState(initial?.enabled ?? false);
  const [smtpHost, setSmtpHost] = useState((cfg.smtp_host as string) ?? "");
  const [smtpPort, setSmtpPort] = useState(
    (cfg.smtp_port as number) ?? 587
  );
  const [fromAddr, setFromAddr] = useState((cfg.from_addr as string) ?? "");
  const [toAddrs, setToAddrs] = useState(
    ((cfg.to_addrs as string[]) ?? []).join(", ")
  );
  const [smtpUser, setSmtpUser] = useState((cfg.smtp_user as string) ?? "");
  const [smtpPassword, setSmtpPassword] = useState(
    (cfg.smtp_password as string) ?? ""
  );
  const [useTls, setUseTls] = useState((cfg.use_tls as boolean) ?? true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setDirty(true);
  }, [enabled, smtpHost, smtpPort, fromAddr, toAddrs, smtpUser, smtpPassword, useTls]);

  const save = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const r = await fetch(`${API}/notifications/settings/email`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled,
          config: {
            smtp_host: smtpHost,
            smtp_port: smtpPort,
            from_addr: fromAddr,
            to_addrs: toAddrs
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            smtp_user: smtpUser,
            smtp_password: smtpPassword,
            use_tls: useTls,
          },
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      setFeedback({ ok: true, msg: "Saved" });
      setDirty(false);
      onSaved();
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setFeedback(null);
    try {
      const r = await fetch(`${API}/notifications/test/email`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(await r.text());
      setFeedback({ ok: true, msg: "Test email sent!" });
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Test failed",
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-lg font-medium">Email</h3>
        <Toggle checked={enabled} onChange={setEnabled} />
      </div>
      <div className="space-y-3 text-sm">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-[var(--muted)]">SMTP Host</label>
            <input
              value={smtpHost}
              onChange={(e) => setSmtpHost(e.target.value)}
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
              placeholder="smtp.gmail.com"
            />
          </div>
          <div>
            <label className="mb-1 block text-[var(--muted)]">SMTP Port</label>
            <input
              type="number"
              value={smtpPort}
              onChange={(e) => setSmtpPort(Number(e.target.value))}
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
            />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[var(--muted)]">From Address</label>
          <input
            value={fromAddr}
            onChange={(e) => setFromAddr(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
            placeholder="argus@example.com"
          />
        </div>
        <div>
          <label className="mb-1 block text-[var(--muted)]">
            To Addresses (comma-separated)
          </label>
          <input
            value={toAddrs}
            onChange={(e) => setToAddrs(e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
            placeholder="admin@example.com, ops@example.com"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-[var(--muted)]">
              SMTP Username
            </label>
            <input
              value={smtpUser}
              onChange={(e) => setSmtpUser(e.target.value)}
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-[var(--muted)]">
              SMTP Password
            </label>
            <input
              type="password"
              value={smtpPassword}
              onChange={(e) => setSmtpPassword(e.target.value)}
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm"
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[var(--muted)]">Use TLS</label>
          <Toggle checked={useTls} onChange={setUseTls} />
        </div>
        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="rounded bg-[var(--accent)] px-4 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <button
            onClick={test}
            disabled={testing}
            className="rounded border border-[var(--border)] px-4 py-1.5 text-sm hover:opacity-80 disabled:opacity-40"
          >
            {testing ? "Testing..." : "Test"}
          </button>
          {feedback && (
            <span
              className={`text-sm ${feedback.ok ? "text-green-400" : "text-red-400"}`}
            >
              {feedback.msg}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Page                                                          */
/* ------------------------------------------------------------------ */
export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [notifConfigs, setNotifConfigs] = useState<ChannelConfig[]>([]);
  const [error, setError] = useState("");

  const loadSettings = useCallback(async () => {
    try {
      const r = await fetch(`${API}/settings`);
      const data = await r.json();
      setSettings(data);
      setNotifConfigs(data.notifications ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const reloadNotifs = async () => {
    try {
      const r = await fetch(`${API}/notifications/settings`);
      const data = await r.json();
      setNotifConfigs(data.channels ?? []);
    } catch {
      // silent
    }
  };

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

  const slackCfg = notifConfigs.find((c) => c.channel_type === "slack");
  const emailCfg = notifConfigs.find((c) => c.channel_type === "email");

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h2 className="mb-6 text-xl font-semibold">Settings</h2>

      {/* LLM Provider — editable */}
      <LLMSection initial={settings.llm} onSaved={loadSettings} />

      {/* Budget — editable */}
      {settings.budget && Object.keys(settings.budget).length > 0 && (
        <BudgetSection initial={settings.budget} onSaved={loadSettings} />
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

      {/* Notifications — editable */}
      <h3 className="mb-3 text-lg font-semibold">Notifications</h3>

      <SlackSection initial={slackCfg} onSaved={reloadNotifs} />
      <EmailSection initial={emailCfg} onSaved={reloadNotifs} />

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
