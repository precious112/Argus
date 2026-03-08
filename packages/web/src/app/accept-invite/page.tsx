"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function AcceptInviteContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [validating, setValidating] = useState(true);
  const [invitation, setInvitation] = useState<{
    email: string;
    role: string;
    has_account: boolean;
  } | null>(null);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  useEffect(() => {
    if (!token) {
      setError("No invitation token provided");
      setValidating(false);
      return;
    }

    // Check if the user is already logged in
    const checkAuth = fetch(`${apiBase}/api/v1/auth/me`, {
      credentials: "include",
    })
      .then((r) => {
        if (r.ok) setIsLoggedIn(true);
      })
      .catch(() => {});

    // Validate the token
    const validateToken = fetch(
      `${apiBase}/api/v1/auth/accept-invite/validate?token=${token}`
    )
      .then((res) => {
        if (!res.ok) throw new Error("Invalid or expired invitation");
        return res.json();
      })
      .then((data) => {
        setInvitation({
          email: data.email,
          role: data.role,
          has_account: data.has_account ?? false,
        });
      })
      .catch(() => {
        setError("This invitation is invalid or has expired");
      });

    Promise.all([checkAuth, validateToken]).finally(() => setValidating(false));
  }, [token, apiBase]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const payload: Record<string, string> = { token };
      // Only send username/password when creating a new account
      if (!invitation?.has_account) {
        payload.username = username;
        payload.password = password;
      } else if (!isLoggedIn) {
        // Existing account, not logged in — send password for verification
        payload.password = password;
      }
      // If logged in + has_account, just send the token

      const res = await fetch(`${apiBase}/api/v1/auth/accept-invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to accept invitation");
        return;
      }

      router.push("/");
    } catch {
      setError("Unable to connect to server");
    } finally {
      setLoading(false);
    }
  }

  if (validating) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
        <p className="text-sm text-[var(--muted)]">Validating invitation...</p>
      </div>
    );
  }

  if (!invitation) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
        <div className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center">
          <h1 className="mb-2 text-xl font-semibold">Invalid Invitation</h1>
          <p className="mb-4 text-sm text-[var(--muted)]">{error}</p>
          <a
            href="/login"
            className="text-sm text-argus-400 hover:text-argus-300"
          >
            Go to login
          </a>
        </div>
      </div>
    );
  }

  // Determine which form to show
  const showUsernameField = !invitation.has_account;
  const showPasswordField = !invitation.has_account || !isLoggedIn;
  const buttonLabel = invitation.has_account
    ? isLoggedIn
      ? "Join organization"
      : "Verify & join"
    : "Accept & join team";

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
      <div className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-8">
        <div className="mb-6 flex flex-col items-center gap-2">
          <img src="/argus-logo.png" alt="Argus" className="h-10 w-auto" />
          <h1 className="text-xl font-semibold">Join your team</h1>
          <p className="text-sm text-[var(--muted)]">
            You&apos;ve been invited as <span className="font-medium text-[var(--foreground)]">{invitation.role}</span>
          </p>
          <p className="text-xs text-[var(--muted)]">{invitation.email}</p>
          {invitation.has_account && isLoggedIn && (
            <p className="text-xs text-emerald-400">You&apos;re signed in — click below to join.</p>
          )}
          {invitation.has_account && !isLoggedIn && (
            <p className="text-xs text-amber-400">Enter your password to confirm your identity.</p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {showUsernameField && (
            <div>
              <label
                htmlFor="username"
                className="mb-1 block text-sm text-[var(--muted)]"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 text-sm focus:border-argus-500 focus:outline-none"
              />
            </div>
          )}

          {showPasswordField && (
            <div>
              <label
                htmlFor="password"
                className="mb-1 block text-sm text-[var(--muted)]"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete={invitation.has_account ? "current-password" : "new-password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 text-sm focus:border-argus-500 focus:outline-none"
              />
            </div>
          )}

          {error && <p className="text-sm text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded bg-argus-600 px-4 py-2 text-sm font-medium text-white hover:bg-argus-500 disabled:opacity-50"
          >
            {loading ? "Joining..." : buttonLabel}
          </button>
        </form>

        {!invitation.has_account && (
          <p className="mt-4 text-center text-sm text-[var(--muted)]">
            Already have an account?{" "}
            <a href="/login" className="text-argus-400 hover:text-argus-300">
              Sign in
            </a>
          </p>
        )}
      </div>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
          <p className="text-sm text-[var(--muted)]">Loading...</p>
        </div>
      }
    >
      <AcceptInviteContent />
    </Suspense>
  );
}
