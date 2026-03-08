"use client";

import type { ReactNode } from "react";
import { LicenseContext, useLicenseLoader } from "@/hooks/useLicense";

export function LicenseProvider({ children }: { children: ReactNode }) {
  const value = useLicenseLoader();

  return (
    <LicenseContext.Provider value={value}>{children}</LicenseContext.Provider>
  );
}
