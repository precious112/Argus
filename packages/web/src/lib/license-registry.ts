/**
 * Frontend mirror of the backend FEATURE_REGISTRY.
 * Maps each feature key to its minimum required edition.
 */
import type { Edition } from "./license";

export const FEATURE_REGISTRY: Record<string, Edition> = {
  // Community
  host_monitoring: "community",
  log_analysis: "community",
  basic_alerting: "community",
  ai_chat: "community",
  sdk_telemetry: "community",
  // Pro
  team_management: "pro",
  advanced_integrations: "pro",
  custom_dashboards: "pro",
  priority_support: "pro",
  // Enterprise
  multi_tenancy: "enterprise",
  sso_saml: "enterprise",
  advanced_analytics: "enterprise",
  sla_monitoring: "enterprise",
  audit_log_export: "enterprise",
};
