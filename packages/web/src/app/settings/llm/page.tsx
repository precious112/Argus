"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

const API =
  process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:7600/api/v1";

interface LLMConfig {
  configured: boolean;
  provider: string;
  model: string;
  base_url: string;
  has_api_key: boolean;
}

export default function LLMSettingsPage() {
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(
    null
  );
  const [loading, setLoading] = useState(true);

  const loadConfig = useCallback(async () => {
    try {
      const res = await apiFetch(`${API}/llm-config`);
      if (res.ok) {
        const data: LLMConfig = await res.json();
        setConfig(data);
        if (data.configured) {
          setProvider(data.provider);
          setModel(data.model);
          setBaseUrl(data.base_url);
        }
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  async function handleSave() {
    setSaving(true);
    setFeedback(null);
    try {
      const res = await apiFetch(`${API}/llm-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          api_key: apiKey,
          model,
          base_url: baseUrl,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Save failed");
      }
      setFeedback({ ok: true, msg: "Configuration saved" });
      setApiKey("");
      await loadConfig();
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setFeedback(null);
    try {
      const res = await apiFetch(`${API}/llm-config`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      setFeedback({ ok: true, msg: "Custom configuration removed" });
      setProvider("openai");
      setModel("");
      setApiKey("");
      setBaseUrl("");
      await loadConfig();
    } catch (e: unknown) {
      setFeedback({
        ok: false,
        msg: e instanceof Error ? e.message : "Delete failed",
      });
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <h2 className="mb-6 text-xl font-semibold">LLM Configuration</h2>
        <p className="text-[var(--muted)]">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h2 className="mb-2 text-xl font-semibold">LLM Configuration</h2>
      <p className="mb-6 text-sm text-[var(--muted)]">
        Bring your own LLM API key. If not configured, the platform default will
        be used.
      </p>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-6">
        {config?.configured && (
          <div className="mb-4 rounded bg-green-900/20 px-3 py-2 text-sm text-green-400">
            Custom LLM configuration active ({config.provider})
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm text-[var(--muted)]">
              Provider
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Google Gemini</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-sm text-[var(--muted)]">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                config?.has_api_key
                  ? "Configured (leave blank to keep)"
                  : "Enter your API key"
              }
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-sm focus:border-argus-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm text-[var(--muted)]">
              Model
            </label>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o"
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-sm focus:border-argus-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm text-[var(--muted)]">
              Base URL (optional)
            </label>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="Leave empty for default"
              className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-sm focus:border-argus-500 focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded bg-argus-600 px-4 py-2 text-sm font-medium text-white hover:bg-argus-500 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Configuration"}
            </button>
            {config?.configured && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="rounded border border-red-800 px-4 py-2 text-sm text-red-400 hover:bg-red-900/20 disabled:opacity-50"
              >
                {deleting ? "Removing..." : "Remove Custom Config"}
              </button>
            )}
          </div>

          {feedback && (
            <p
              className={`text-sm ${feedback.ok ? "text-green-400" : "text-red-400"}`}
            >
              {feedback.msg}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
