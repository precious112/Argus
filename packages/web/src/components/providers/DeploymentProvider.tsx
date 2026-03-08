"use client";

import type { ReactNode } from "react";
import { DeploymentContext, useDeploymentLoader } from "@/hooks/useDeployment";

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const value = useDeploymentLoader();

  return (
    <DeploymentContext.Provider value={value}>
      {children}
    </DeploymentContext.Provider>
  );
}
