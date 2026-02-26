/**
 * License types and utilities for Argus open-core feature gating.
 */

export type Edition = "community" | "pro" | "enterprise";

export interface LicenseInfo {
  edition: Edition;
  holder: string;
  expires_at: string | null;
  max_nodes: number;
  valid: boolean;
  error: string;
  features: string[];
}

const EDITION_ORDER: Record<Edition, number> = {
  community: 0,
  pro: 1,
  enterprise: 2,
};

/** Check if a feature string is present in the license info. */
export function isFeatureEnabled(
  license: LicenseInfo | null,
  feature: string,
): boolean {
  if (!license) return false;
  return license.features.includes(feature);
}

/** Human-friendly edition label. */
export function editionLabel(edition: Edition): string {
  switch (edition) {
    case "community":
      return "Community";
    case "pro":
      return "Pro";
    case "enterprise":
      return "Enterprise";
    default:
      return "Community";
  }
}

/** Check if the current edition meets or exceeds the required edition. */
export function editionAtLeast(
  current: Edition,
  required: Edition,
): boolean {
  return EDITION_ORDER[current] >= EDITION_ORDER[required];
}
