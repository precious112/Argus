"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDeployment } from "@/hooks/useDeployment";

const apiBase = process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

interface SlackStatus {
  connected: boolean;
  team_name?: string;
  team_id?: string;
  channel_id?: string;
  channel_name?: string;
}

interface SlackChannel {
  id: string;
  name: string;
  is_private: boolean;
}

const SlackIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
    <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zm-1.27 0a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.163 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.163 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.163 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zm0-1.27a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.315A2.528 2.528 0 0 1 24 15.163a2.528 2.528 0 0 1-2.522 2.523h-6.315z" />
  </svg>
);

export default function IntegrationsPage() {
  const { isSaaS } = useDeployment();
  const searchParams = useSearchParams();

  const [status, setStatus] = useState<SlackStatus>({ connected: false });
  const [channels, setChannels] = useState<SlackChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingChannels, setLoadingChannels] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showChannelPicker, setShowChannelPicker] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/integrations/slack/status`, {
        credentials: "include",
      });
      if (res.ok) {
        setStatus(await res.json());
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Show toast on redirect from OAuth
  useEffect(() => {
    const slackParam = searchParams.get("slack");
    if (slackParam === "connected") {
      setToast("Slack connected successfully!");
      fetchStatus();
    } else if (slackParam === "error") {
      setToast("Failed to connect Slack. Please try again.");
    }
  }, [searchParams, fetchStatus]);

  // Auto-dismiss toast
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 5000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  async function handleConnect() {
    try {
      const res = await fetch(`${apiBase}/api/v1/integrations/slack/authorize`, {
        credentials: "include",
      });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      }
    } catch {
      setToast("Failed to start Slack authorization.");
    }
  }

  async function handleDisconnect() {
    try {
      await fetch(`${apiBase}/api/v1/integrations/slack/disconnect`, {
        method: "POST",
        credentials: "include",
      });
      setStatus({ connected: false });
      setToast("Slack disconnected.");
    } catch {
      setToast("Failed to disconnect Slack.");
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch(`${apiBase}/api/v1/integrations/slack/test`, {
        method: "POST",
        credentials: "include",
      });
      const data = await res.json();
      setTestResult(data.ok ? "Test message sent!" : `Error: ${data.error}`);
    } catch {
      setTestResult("Failed to send test message.");
    } finally {
      setTesting(false);
    }
  }

  async function handleOpenChannelPicker() {
    setShowChannelPicker(true);
    setLoadingChannels(true);
    try {
      const res = await fetch(`${apiBase}/api/v1/integrations/slack/channels`, {
        credentials: "include",
      });
      const data = await res.json();
      setChannels(data.channels || []);
    } catch {
      setChannels([]);
    } finally {
      setLoadingChannels(false);
    }
  }

  async function handleSelectChannel(ch: SlackChannel) {
    try {
      await fetch(`${apiBase}/api/v1/integrations/slack/channel`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id: ch.id, channel_name: ch.name }),
      });
      setStatus((prev) => ({ ...prev, channel_id: ch.id, channel_name: ch.name }));
      setShowChannelPicker(false);
      setToast(`Channel set to #${ch.name}`);
    } catch {
      setToast("Failed to update channel.");
    }
  }

  if (!isSaaS) {
    return (
      <div className="flex-1 p-6">
        <h1 className="text-2xl font-bold mb-4">Integrations</h1>
        <p className="text-[var(--muted)]">
          Integrations management is available in SaaS mode. Use the Settings page to configure Slack manually.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 rounded-lg bg-[var(--card)] border border-[var(--border)] px-4 py-3 shadow-lg text-sm">
          {toast}
        </div>
      )}

      <h1 className="text-2xl font-bold mb-6">Integrations</h1>

      {/* Slack Card */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-6 max-w-2xl">
        <div className="flex items-center gap-3 mb-4">
          <div className="text-[#E01E5A]">
            <SlackIcon />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Slack</h2>
            <p className="text-sm text-[var(--muted)]">
              Receive alerts and investigation reports in your Slack workspace.
            </p>
          </div>
          <div className="ml-auto">
            {loading ? (
              <span className="text-xs text-[var(--muted)]">Loading...</span>
            ) : status.connected ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Connected
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-500/10 px-2.5 py-0.5 text-xs font-medium text-gray-400">
                <span className="h-1.5 w-1.5 rounded-full bg-gray-500" />
                Not connected
              </span>
            )}
          </div>
        </div>

        {!loading && !status.connected && (
          <button
            onClick={handleConnect}
            className="rounded-md bg-[#4A154B] px-4 py-2 text-sm font-medium text-white hover:bg-[#611f69] transition-colors"
          >
            Add to Slack
          </button>
        )}

        {!loading && status.connected && (
          <div className="space-y-4">
            {/* Workspace info */}
            <div className="text-sm">
              <span className="text-[var(--muted)]">Workspace:</span>{" "}
              <span className="font-medium">{status.team_name}</span>
            </div>

            {/* Channel */}
            <div className="text-sm flex items-center gap-2">
              <span className="text-[var(--muted)]">Alert channel:</span>
              {status.channel_name ? (
                <span className="font-medium">#{status.channel_name}</span>
              ) : (
                <span className="text-yellow-400 text-xs">Not set</span>
              )}
              <button
                onClick={handleOpenChannelPicker}
                className="rounded border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--foreground)] transition-colors"
              >
                {status.channel_name ? "Change" : "Select channel"}
              </button>
            </div>

            {/* Channel picker dropdown */}
            {showChannelPicker && (
              <div className="rounded border border-[var(--border)] bg-[var(--background)] p-3 max-h-48 overflow-y-auto">
                {loadingChannels ? (
                  <p className="text-xs text-[var(--muted)]">Loading channels...</p>
                ) : channels.length === 0 ? (
                  <p className="text-xs text-[var(--muted)]">No channels found. Make sure the bot is invited to at least one channel.</p>
                ) : (
                  <div className="space-y-1">
                    {channels.map((ch) => (
                      <button
                        key={ch.id}
                        onClick={() => handleSelectChannel(ch)}
                        className="w-full text-left rounded px-2 py-1 text-sm hover:bg-[var(--card)] transition-colors"
                      >
                        {ch.is_private ? "🔒 " : "#"}{ch.name}
                      </button>
                    ))}
                  </div>
                )}
                <button
                  onClick={() => setShowChannelPicker(false)}
                  className="mt-2 text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  Cancel
                </button>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2 border-t border-[var(--border)]">
              <button
                onClick={handleTest}
                disabled={testing || !status.channel_id}
                className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--card)] transition-colors disabled:opacity-50"
              >
                {testing ? "Sending..." : "Test"}
              </button>
              <button
                onClick={handleDisconnect}
                className="rounded-md border border-red-600/40 px-3 py-1.5 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
              >
                Disconnect
              </button>
              {testResult && (
                <span className={`text-xs ${testResult.startsWith("Error") ? "text-red-400" : "text-emerald-400"}`}>
                  {testResult}
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Future integrations placeholder */}
      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4 max-w-2xl">
        {[
          { name: "PagerDuty", desc: "Route alerts to PagerDuty incidents" },
          { name: "Discord", desc: "Send alerts to Discord channels" },
          { name: "Microsoft Teams", desc: "Push alerts to Teams channels" },
        ].map((integration) => (
          <div
            key={integration.name}
            className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 opacity-50"
          >
            <h3 className="text-sm font-semibold">{integration.name}</h3>
            <p className="text-xs text-[var(--muted)] mt-1">{integration.desc}</p>
            <span className="mt-2 inline-block rounded bg-[var(--background)] px-2 py-0.5 text-[10px] text-[var(--muted)]">
              Coming soon
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
