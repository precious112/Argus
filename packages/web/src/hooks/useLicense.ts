"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { Edition, LicenseInfo } from "@/lib/license";
import { isFeatureEnabled } from "@/lib/license";

export interface LicenseContextValue {
  license: LicenseInfo | null;
  edition: Edition;
  loading: boolean;
  hasFeature: (feature: string) => boolean;
  refresh: () => Promise<void>;
}

const DEFAULT_CONTEXT: LicenseContextValue = {
  license: null,
  edition: "community",
  loading: true,
  hasFeature: () => false,
  refresh: async () => {},
};

export const LicenseContext =
  createContext<LicenseContextValue>(DEFAULT_CONTEXT);

export function useLicense(): LicenseContextValue {
  return useContext(LicenseContext);
}

/** Hook that fetches license info from the backend. Used by LicenseProvider. */
export function useLicenseLoader(): LicenseContextValue {
  const [license, setLicense] = useState<LicenseInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  const fetchLicense = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/license`, {
        credentials: "include",
      });
      if (res.ok) {
        const data: LicenseInfo = await res.json();
        setLicense(data);
      }
    } catch {
      // Silently fall back to community
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchLicense();
  }, [fetchLicense]);

  const hasFeature = useCallback(
    (feature: string) => isFeatureEnabled(license, feature),
    [license],
  );

  return {
    license,
    edition: license?.edition ?? "community",
    loading,
    hasFeature,
    refresh: fetchLicense,
  };
}
