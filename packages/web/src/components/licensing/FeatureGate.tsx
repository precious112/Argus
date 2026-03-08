"use client";

import type { ReactNode } from "react";
import { useLicense } from "@/hooks/useLicense";
import { editionLabel } from "@/lib/license";
import { FEATURE_REGISTRY } from "@/lib/license-registry";

interface FeatureGateProps {
  /** The feature key to check (e.g. "team_management"). */
  feature: string;
  /** If true, render nothing when not licensed (instead of upgrade prompt). */
  hide?: boolean;
  children: ReactNode;
}

/**
 * Conditionally renders children based on license.
 * Shows an upgrade prompt by default, or nothing if `hide` is set.
 */
export function FeatureGate({ feature, hide, children }: FeatureGateProps) {
  const { hasFeature } = useLicense();

  if (hasFeature(feature)) {
    return <>{children}</>;
  }

  if (hide) return null;

  const requiredEdition = FEATURE_REGISTRY[feature] ?? "pro";

  return (
    <div className="flex items-center gap-2 rounded border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--muted)]">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 20 20"
        fill="currentColor"
        className="h-4 w-4 flex-shrink-0"
      >
        <path
          fillRule="evenodd"
          d="M10 1a4.5 4.5 0 0 0-4.5 4.5V9H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-.5V5.5A4.5 4.5 0 0 0 10 1Zm3 8V5.5a3 3 0 1 0-6 0V9h6Z"
          clipRule="evenodd"
        />
      </svg>
      <span>Requires Argus {editionLabel(requiredEdition)}</span>
    </div>
  );
}
