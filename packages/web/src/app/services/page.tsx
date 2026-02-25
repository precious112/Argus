"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
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

const API_BASE =
  process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";

export default function ServicesPage() {
  const [services, setServices] = useState<ServiceSummary[]>([]);
  const [selectedService, setSelectedService] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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
    // Refresh every 30s
    const timer = setInterval(fetchServices, 30000);
    return () => clearInterval(timer);
  }, []);

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
        <span className="text-sm text-[var(--muted)]">
          {services.length} service{services.length !== 1 ? "s" : ""} active
        </span>
      </div>

      {services.length === 0 ? (
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
            {services.map((svc) => (
              <ServiceCard
                key={svc.service}
                service={svc}
                onClick={() => setSelectedService(svc.service)}
              />
            ))}
          </div>

          {/* Service detail panel */}
          <div className="flex-1 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
            {selectedService ? (
              <ServiceMetricsPanel
                service={selectedService}
                apiBase={API_BASE}
              />
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
