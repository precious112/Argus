"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function VerifyEmailInner() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading"
  );
  const [message, setMessage] = useState("");

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  useEffect(() => {
    const token = searchParams.get("token");
    if (!token) {
      setStatus("error");
      setMessage("Missing verification token");
      return;
    }

    fetch(`${apiBase}/api/v1/auth/verify-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then((res) => {
        if (!res.ok) return res.json().then((d) => Promise.reject(d));
        return res.json();
      })
      .then(() => {
        setStatus("success");
        setMessage("Your email has been verified successfully!");
      })
      .catch((err) => {
        setStatus("error");
        setMessage(err?.detail || "Verification failed");
      });
  }, [searchParams, apiBase]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
      <div className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center">
        <div className="mb-6 flex flex-col items-center gap-2">
          <img src="/argus-logo.png" alt="Argus" className="h-10 w-auto" />
        </div>

        {status === "loading" && (
          <p className="text-[var(--muted)]">Verifying your email...</p>
        )}

        {status === "success" && (
          <>
            <p className="mb-4 text-green-400">{message}</p>
            <a
              href="/login"
              className="text-argus-400 hover:text-argus-300"
            >
              Continue to sign in
            </a>
          </>
        )}

        {status === "error" && (
          <>
            <p className="mb-4 text-red-400">{message}</p>
            <a
              href="/login"
              className="text-argus-400 hover:text-argus-300"
            >
              Back to login
            </a>
          </>
        )}
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[var(--background)]">
          <p className="text-[var(--muted)]">Loading...</p>
        </div>
      }
    >
      <VerifyEmailInner />
    </Suspense>
  );
}
