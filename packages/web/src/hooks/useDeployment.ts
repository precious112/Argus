"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

export interface DeploymentInfo {
  mode: string;
  billing_provider: string | null;
  registration_enabled: boolean;
}

export interface DeploymentContextValue {
  deployment: DeploymentInfo | null;
  isSaaS: boolean;
  billingProvider: string | null;
  registrationEnabled: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
}

const DEFAULT_CONTEXT: DeploymentContextValue = {
  deployment: null,
  isSaaS: false,
  billingProvider: null,
  registrationEnabled: false,
  loading: true,
  refresh: async () => {},
};

export const DeploymentContext =
  createContext<DeploymentContextValue>(DEFAULT_CONTEXT);

export function useDeployment(): DeploymentContextValue {
  return useContext(DeploymentContext);
}

/** Hook that fetches deployment info from the backend. Used by DeploymentProvider. */
export function useDeploymentLoader(): DeploymentContextValue {
  const [deployment, setDeployment] = useState<DeploymentInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const apiBase =
    process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

  const fetchDeployment = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/deployment-info`, {
        credentials: "include",
      });
      if (res.ok) {
        const data: DeploymentInfo = await res.json();
        setDeployment(data);
      }
    } catch {
      // Silently fall back to self-hosted defaults
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchDeployment();
  }, [fetchDeployment]);

  return {
    deployment,
    isSaaS: deployment?.mode === "saas",
    billingProvider: deployment?.billing_provider ?? null,
    registrationEnabled: deployment?.registration_enabled ?? false,
    loading,
    refresh: fetchDeployment,
  };
}
