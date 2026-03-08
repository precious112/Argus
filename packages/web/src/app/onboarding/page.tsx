"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface OnboardingStatus {
  dismissed: boolean;
  completed: boolean;
  steps: {
    create_api_key: boolean;
    install_sdk: boolean;
    configure_webhook: boolean;
  };
}

export default function OnboardingPage() {
  const router = useRouter();
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  useEffect(() => {
    fetch(`${apiBase}/api/v1/onboarding/status`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        setStatus(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [apiBase]);

  async function handleDismiss() {
    await fetch(`${apiBase}/api/v1/onboarding/dismiss`, {
      method: "POST",
      credentials: "include",
    });
    router.push("/");
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-[var(--muted)]">Loading...</p>
      </div>
    );
  }

  const steps = [
    {
      key: "create_api_key",
      title: "Create an API Key",
      description:
        "Generate an API key to authenticate your SDK. Go to Keys to create one.",
      href: "/keys",
      done: status?.steps.create_api_key ?? false,
    },
    {
      key: "install_sdk",
      title: "Install the SDK",
      description:
        "Add the Argus SDK to your application. Use pip install argus or npm install @argus/sdk.",
      href: "/keys",
      done: status?.steps.install_sdk ?? false,
    },
    {
      key: "configure_webhook",
      title: "Configure a Webhook",
      description:
        "Set up a webhook endpoint so the AI agent can execute tools in your environment.",
      href: "/webhooks",
      done: status?.steps.configure_webhook ?? false,
    },
  ];

  const completedCount = steps.filter((s) => s.done).length;

  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold">Welcome to Argus</h1>
        <p className="mt-2 text-[var(--muted)]">
          Complete these steps to get started with AI-native observability.
        </p>
        <div className="mt-4 h-2 rounded-full bg-[var(--border)]">
          <div
            className="h-2 rounded-full bg-argus-500 transition-all"
            style={{ width: `${(completedCount / steps.length) * 100}%` }}
          />
        </div>
        <p className="mt-1 text-xs text-[var(--muted)]">
          {completedCount} of {steps.length} steps completed
        </p>
      </div>

      <div className="space-y-4">
        {steps.map((step) => (
          <div
            key={step.key}
            className={`rounded-lg border p-4 ${
              step.done
                ? "border-green-800 bg-green-900/10"
                : "border-[var(--border)] bg-[var(--card)]"
            }`}
          >
            <div className="flex items-start gap-3">
              <div
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${
                  step.done
                    ? "bg-green-600 text-white"
                    : "border border-[var(--border)] text-[var(--muted)]"
                }`}
              >
                {step.done ? "\u2713" : ""}
              </div>
              <div className="flex-1">
                <h3 className="font-medium">{step.title}</h3>
                <p className="mt-1 text-sm text-[var(--muted)]">
                  {step.description}
                </p>
                {!step.done && (
                  <a
                    href={step.href}
                    className="mt-2 inline-block text-sm text-argus-400 hover:text-argus-300"
                  >
                    Get started &rarr;
                  </a>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-8 flex justify-between">
        <button
          onClick={handleDismiss}
          className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          Skip for now
        </button>
        {status?.completed && (
          <button
            onClick={() => router.push("/")}
            className="rounded bg-argus-600 px-4 py-2 text-sm font-medium text-white hover:bg-argus-500"
          >
            Go to Dashboard
          </button>
        )}
      </div>
    </div>
  );
}
