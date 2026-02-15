"use client";

interface ServiceSummary {
  service: string;
  event_count: number;
  event_type_count: number;
  error_count: number;
  invocation_count: number;
  first_seen: string;
  last_seen: string;
}

interface ServiceCardProps {
  service: ServiceSummary;
  onClick?: () => void;
}

export function ServiceCard({ service, onClick }: ServiceCardProps) {
  const errorRate =
    service.invocation_count > 0
      ? ((service.error_count / service.invocation_count) * 100).toFixed(1)
      : "0.0";

  const isHealthy = service.error_count === 0;
  const hasErrors = service.error_count > 0;

  return (
    <div
      className="cursor-pointer rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 transition-colors hover:border-argus-500/50"
      onClick={onClick}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{service.service}</h3>
        <span
          className={`h-2 w-2 rounded-full ${
            isHealthy ? "bg-green-500" : "bg-red-500"
          }`}
        />
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs text-[var(--muted)]">
        <div>
          <span className="block text-lg font-bold text-[var(--foreground)]">
            {service.invocation_count.toLocaleString()}
          </span>
          Invocations
        </div>
        <div>
          <span
            className={`block text-lg font-bold ${
              hasErrors ? "text-red-400" : "text-[var(--foreground)]"
            }`}
          >
            {errorRate}%
          </span>
          Error Rate
        </div>
        <div>
          <span className="block text-lg font-bold text-[var(--foreground)]">
            {service.event_count.toLocaleString()}
          </span>
          Total Events
        </div>
        <div>
          <span
            className={`block text-lg font-bold ${
              hasErrors ? "text-red-400" : "text-green-400"
            }`}
          >
            {service.error_count}
          </span>
          Errors
        </div>
      </div>

      <div className="mt-3 text-xs text-[var(--muted)]">
        Last seen: {new Date(service.last_seen).toLocaleString()}
      </div>
    </div>
  );
}
