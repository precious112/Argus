"use client";

import type { ActionRequest } from "@/lib/protocol";

const RISK_COLORS: Record<string, string> = {
  READ_ONLY: "bg-green-600",
  LOW: "bg-blue-600",
  MEDIUM: "bg-yellow-600",
  HIGH: "bg-orange-600",
  CRITICAL: "bg-red-600",
};

interface ActionApprovalProps {
  action: ActionRequest;
  onApprove: (actionId: string) => void;
  onReject: (actionId: string) => void;
  resolved?: boolean;
}

export function ActionApproval({
  action,
  onApprove,
  onReject,
  resolved,
}: ActionApprovalProps) {
  const isCritical = action.risk_level === "CRITICAL";
  const borderClass = isCritical
    ? "border-red-500"
    : "border-[var(--border)]";
  const riskColor = RISK_COLORS[action.risk_level] || "bg-gray-600";

  const commandStr = Array.isArray(action.command)
    ? action.command.join(" ")
    : action.command;

  return (
    <div
      className={`rounded-lg border-2 ${borderClass} bg-[var(--card)] p-4`}
    >
      <div className="mb-2 flex items-center gap-2">
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold text-white ${riskColor}`}
        >
          {action.risk_level}
        </span>
        <span className="text-sm font-medium text-[var(--foreground)]">
          Action Approval Required
        </span>
      </div>

      <p className="mb-2 text-sm text-[var(--foreground)]">
        {action.description}
      </p>

      <pre className="mb-3 rounded bg-black/30 px-3 py-2 text-xs text-green-400">
        $ {commandStr}
      </pre>

      {isCritical && (
        <p className="mb-3 text-xs font-semibold text-red-400">
          Warning: This is a CRITICAL action and may cause data loss or
          service disruption.
        </p>
      )}

      {!resolved && (
        <div className="flex gap-2">
          <button
            onClick={() => onApprove(action.id)}
            className="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700"
          >
            Approve
          </button>
          <button
            onClick={() => onReject(action.id)}
            className="rounded bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
