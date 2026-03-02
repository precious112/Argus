"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

function GoogleCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setError("No authorization code received");
      return;
    }

    fetch(`${apiBase}/api/v1/auth/oauth/google/callback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ code }),
    })
      .then((res) => {
        if (!res.ok) return res.json().then((d) => Promise.reject(d));
        return res.json();
      })
      .then(() => router.push("/"))
      .catch((err) => {
        setError(err?.detail || "OAuth login failed");
      });
  }, [searchParams, apiBase, router]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
        <div className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center">
          <p className="mb-4 text-red-400">{error}</p>
          <a href="/login" className="text-argus-400 hover:text-argus-300">
            Back to login
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
      <p className="text-[var(--muted)]">Signing in with Google...</p>
    </div>
  );
}

export default function GoogleCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
          <p className="text-[var(--muted)]">Loading...</p>
        </div>
      }
    >
      <GoogleCallbackInner />
    </Suspense>
  );
}
