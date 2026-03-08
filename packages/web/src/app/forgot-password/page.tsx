"use client";

import { FormEvent, useState } from "react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${apiBase}/api/v1/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Request failed");
        return;
      }

      setSuccess(true);
    } catch {
      setError("Unable to connect to server");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
      <div className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-8">
        <div className="mb-6 flex flex-col items-center gap-2">
          <img src="/argus-logo.png" alt="Argus" className="h-10 w-auto" />
          <h1 className="text-xl font-semibold">Reset your password</h1>
        </div>

        {success ? (
          <div className="text-center">
            <p className="mb-4 text-sm text-[var(--muted)]">
              If an account with that email exists, we&apos;ve sent a password
              reset link. Please check your inbox.
            </p>
            <a
              href="/login"
              className="text-sm text-argus-400 hover:text-argus-300"
            >
              Back to login
            </a>
          </div>
        ) : (
          <>
            <p className="mb-4 text-sm text-[var(--muted)]">
              Enter your email address and we&apos;ll send you a link to reset
              your password.
            </p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label
                  htmlFor="email"
                  className="mb-1 block text-sm text-[var(--muted)]"
                >
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 text-sm focus:border-argus-500 focus:outline-none"
                />
              </div>

              {error && <p className="text-sm text-red-400">{error}</p>}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded bg-argus-600 px-4 py-2 text-sm font-medium text-white hover:bg-argus-500 disabled:opacity-50"
              >
                {loading ? "Sending..." : "Send reset link"}
              </button>
            </form>

            <p className="mt-4 text-center text-sm text-[var(--muted)]">
              <a
                href="/login"
                className="text-argus-400 hover:text-argus-300"
              >
                Back to login
              </a>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
