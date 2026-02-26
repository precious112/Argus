"use client";

import type { ReactNode } from "react";
import { LicenseProvider } from "./LicenseProvider";

/** Client-side providers wrapper for the root layout (Server Component). */
export function Providers({ children }: { children: ReactNode }) {
  return <LicenseProvider>{children}</LicenseProvider>;
}
