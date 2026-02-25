"use client";

import type { AlertData } from "@/lib/protocol";

interface AlertBannerProps {
  alerts: AlertData[];
  onDismiss: (alertId: string) => void;
  onAcknowledge?: (alertId: string) => void;
}

export function AlertBanner({ alerts, onDismiss, onAcknowledge }: AlertBannerProps) {
  // Filter out acknowledged/resolved alerts from display
  const visibleAlerts = alerts.filter(
    (a) => !a.status || a.status === "active",
  );

  if (visibleAlerts.length === 0) return null;

  return (
    <div className="space-y-1 px-4 py-2">
      {visibleAlerts.slice(0, 5).map((alert) => (
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
          <div className="ml-3 flex shrink-0 items-center gap-1">
            {onAcknowledge && (
              <button
                onClick={() => onAcknowledge(alert.id)}
                className="rounded px-1.5 py-0.5 text-xs opacity-60 hover:opacity-100 transition-opacity hover:bg-white/10"
                aria-label="Acknowledge alert"
              >
                Ack
              </button>
            )}
            <button
              onClick={() => onDismiss(alert.id)}
              className="rounded px-1.5 py-0.5 text-xs opacity-60 hover:opacity-100 transition-opacity"
              aria-label="Dismiss alert"
            >
              &times;
            </button>
          </div>
        </div>
      ))}
      {visibleAlerts.length > 5 && (
        <div className="text-center text-xs text-[var(--muted)]">
          +{visibleAlerts.length - 5} more alert{visibleAlerts.length - 5 !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
