"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useDeployment } from "@/hooks/useDeployment";
import { ServiceCard } from "@/components/services/ServiceCard";
import { ServiceMetricsPanel } from "@/components/services/ServiceMetricsPanel";

interface ServiceSummary {
  service: string;
  event_count: number;
  event_type_count: number;
  error_count: number;
  invocation_count: number;
  first_seen: string;
  last_seen: string;
}

interface ServiceConfigItem {
  id: string;
  service_name: string;
  environment: string;
  owner_user_id: string;
  description: string;
}

interface TeamMemberItem {
  user_id: string;
  username: string;
  role: string;
}

const API_BASE =
  process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

const ENVIRONMENTS = ["all", "production", "staging", "development"];

export default function ServicesPage() {
  const [services, setServices] = useState<ServiceSummary[]>([]);
  const [serviceConfigs, setServiceConfigs] = useState<ServiceConfigItem[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMemberItem[]>([]);
  const [selectedService, setSelectedService] = useState<string | null>(null);
  const [envFilter, setEnvFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const { isSaaS } = useDeployment();

  useEffect(() => {
    async function fetchServices() {
      try {
        const res = await apiFetch(`${API_BASE}/api/v1/services`);
        const data = await res.json();
        setServices(data.services || []);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    fetchServices();
    const timer = setInterval(fetchServices, 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!isSaaS) return;
    // Fetch service configs and team members for SaaS
    apiFetch(`${API_BASE}/api/v1/service-configs`)
      .then((r) => r.json())
      .then((d) => setServiceConfigs(d.configs || []))
      .catch(() => {});
    apiFetch(`${API_BASE}/api/v1/team/members`)
      .then((r) => r.json())
      .then((d) => setTeamMembers(d.members || []))
      .catch(() => {});
  }, [isSaaS]);

  function getConfig(serviceName: string) {
    return serviceConfigs.find((c) => c.service_name === serviceName);
  }

  function getOwnerName(userId: string) {
    const m = teamMembers.find((t) => t.user_id === userId);
    return m?.username || "";
  }

  async function handleOwnerChange(serviceName: string, ownerId: string) {
    const existing = getConfig(serviceName);
    await apiFetch(`${API_BASE}/api/v1/service-configs/${serviceName}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        service_name: serviceName,
        environment: existing?.environment || "production",
        owner_user_id: ownerId,
        description: existing?.description || "",
      }),
    });
    // Refresh configs
    const res = await apiFetch(`${API_BASE}/api/v1/service-configs`);
    const data = await res.json();
    setServiceConfigs(data.configs || []);
  }

  async function handleEnvChange(serviceName: string, env: string) {
    const existing = getConfig(serviceName);
    await apiFetch(`${API_BASE}/api/v1/service-configs/${serviceName}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        service_name: serviceName,
        environment: env,
        owner_user_id: existing?.owner_user_id || "",
        description: existing?.description || "",
      }),
    });
    const res = await apiFetch(`${API_BASE}/api/v1/service-configs`);
    const data = await res.json();
    setServiceConfigs(data.configs || []);
  }

  // Apply environment filter
  const filteredServices =
    envFilter === "all"
      ? services
      : services.filter((svc) => {
          const cfg = getConfig(svc.service);
          return (cfg?.environment || "production") === envFilter;
        });

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--muted)]">
        Loading services...
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-auto p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">SDK Services</h1>
        <div className="flex items-center gap-3">
          {isSaaS && (
            <div className="flex rounded border border-[var(--border)] text-xs">
              {ENVIRONMENTS.map((env) => (
                <button
                  key={env}
                  onClick={() => setEnvFilter(env)}
                  className={`px-2 py-1 capitalize ${
                    envFilter === env
                      ? "bg-argus-600 text-white"
                      : "hover:bg-[var(--border)]"
                  }`}
                >
                  {env}
                </button>
              ))}
            </div>
          )}
          <span className="text-sm text-[var(--muted)]">
            {filteredServices.length} service
            {filteredServices.length !== 1 ? "s" : ""} active
          </span>
        </div>
      </div>

      {filteredServices.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center text-center text-[var(--muted)]">
          <p className="mb-2 text-lg">No services found</p>
          <p className="text-sm">
            Instrument your application with the Argus SDK to see services here.
          </p>
        </div>
      ) : (
        <div className="flex flex-1 gap-4">
          {/* Service cards grid */}
          <div className="w-80 flex-shrink-0 space-y-3 overflow-auto">
            {filteredServices.map((svc) => {
              const cfg = getConfig(svc.service);
              return (
                <div key={svc.service}>
                  <ServiceCard
                    service={svc}
                    onClick={() => setSelectedService(svc.service)}
                  />
                  {isSaaS && (
                    <div className="mt-1 flex gap-2 px-1 text-xs">
                      <select
                        value={cfg?.environment || "production"}
                        onChange={(e) =>
                          handleEnvChange(svc.service, e.target.value)
                        }
                        className="rounded border border-[var(--border)] bg-transparent px-1 py-0.5"
                      >
                        <option value="production">prod</option>
                        <option value="staging">staging</option>
                        <option value="development">dev</option>
                      </select>
                      <select
                        value={cfg?.owner_user_id || ""}
                        onChange={(e) =>
                          handleOwnerChange(svc.service, e.target.value)
                        }
                        className="flex-1 truncate rounded border border-[var(--border)] bg-transparent px-1 py-0.5"
                      >
                        <option value="">No owner</option>
                        {teamMembers.map((m) => (
                          <option key={m.user_id} value={m.user_id}>
                            {m.username}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Service detail panel */}
          <div className="flex-1 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
            {selectedService ? (
              <div>
                {isSaaS && getConfig(selectedService)?.owner_user_id && (
                  <div className="mb-3 text-xs text-[var(--muted)]">
                    Owner:{" "}
                    {getOwnerName(
                      getConfig(selectedService)!.owner_user_id
                    ) || "Unknown"}
                  </div>
                )}
                <ServiceMetricsPanel
                  service={selectedService}
                  apiBase={API_BASE}
                />
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
                Select a service to view metrics
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
