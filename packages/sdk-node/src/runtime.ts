/**
 * Runtime metrics collector for Node.js applications.
 */

import { getClient } from "./index";

let _timer: ReturnType<typeof setInterval> | null = null;

export function startRuntimeMetrics(intervalMs: number = 30000): void {
  if (_timer) return;

  _timer = setInterval(() => {
    const client = getClient();
    if (!client) return;

    // Memory usage
    const mem = process.memoryUsage();
    client.sendEvent("runtime_metric", {
      metric_name: "heap_used_bytes",
      value: mem.heapUsed,
    });
    client.sendEvent("runtime_metric", {
      metric_name: "heap_total_bytes",
      value: mem.heapTotal,
    });
    client.sendEvent("runtime_metric", {
      metric_name: "rss_bytes",
      value: mem.rss,
    });
    client.sendEvent("runtime_metric", {
      metric_name: "external_bytes",
      value: mem.external,
    });

    // Active handles/requests
    // @ts-expect-error _getActiveHandles is internal
    const handles = process._getActiveHandles?.()?.length ?? 0;
    // @ts-expect-error _getActiveRequests is internal
    const requests = process._getActiveRequests?.()?.length ?? 0;
    client.sendEvent("runtime_metric", {
      metric_name: "active_handles",
      value: handles,
    });
    client.sendEvent("runtime_metric", {
      metric_name: "active_requests",
      value: requests,
    });
  }, intervalMs);
}

export function stopRuntimeMetrics(): void {
  if (_timer) {
    clearInterval(_timer);
    _timer = null;
  }
}
