"use client";

import type { AlertData } from "@/lib/protocol";

interface AlertBannerProps {
  alerts: AlertData[];
  onDismiss: (alertId: string) => void;
}

export function AlertBanner({ alerts, onDismiss }: AlertBannerProps) {
  if (alerts.length === 0) return null;

  return (
    <div className="space-y-1 px-4 py-2">
      {alerts.slice(0, 5).map((alert) => (
        <div
          key={alert.id}
          className={`flex items-start justify-between rounded-lg px-4 py-2 text-sm ${
            alert.severity === "URGENT"
              ? "bg-red-900/30 text-red-300 border border-red-800"
              : "bg-yellow-900/30 text-yellow-300 border border-yellow-800"
          }`}
        >
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  alert.severity === "URGENT"
                    ? "bg-red-500 animate-pulse"
                    : "bg-yellow-500"
                }`}
              />
              <span className="font-medium">{alert.title}</span>
              <span className="text-xs opacity-60">
                {new Date(alert.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <p className="mt-0.5 text-xs opacity-80">{alert.summary}</p>
          </div>
          <button
            onClick={() => onDismiss(alert.id)}
            className="ml-3 shrink-0 rounded px-1.5 py-0.5 text-xs opacity-60 hover:opacity-100 transition-opacity"
            aria-label="Dismiss alert"
          >
            &times;
          </button>
        </div>
      ))}
      {alerts.length > 5 && (
        <div className="text-center text-xs text-[var(--muted)]">
          +{alerts.length - 5} more alert{alerts.length - 5 !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
