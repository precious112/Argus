/**
 * HTTP auto-instrumentation - patches global fetch.
 */

import { getClient } from "../index";
import { getCurrentContext, toTraceparent } from "../context";

let _originalFetch: typeof globalThis.fetch | null = null;

export function patchHttp(): void {
  if (_originalFetch) return;

  _originalFetch = globalThis.fetch;

  globalThis.fetch = async function patchedFetch(
    input: string | Request | URL,
    init?: RequestInit,
  ): Promise<Response> {
    const client = getClient();
    const start = Date.now();
    let statusCode = 0;
    let errorMsg: string | undefined;

    // Determine URL and method
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const method = init?.method || "GET";

    // Inject traceparent header
    const ctx = getCurrentContext();
    if (ctx) {
      const headers = new Headers(init?.headers);
      if (!headers.has("traceparent")) {
        headers.set("traceparent", toTraceparent(ctx));
      }
      init = { ...init, headers };
    }

    try {
      const response = await _originalFetch!(input, init);
      statusCode = response.status;
      return response;
    } catch (err) {
      errorMsg = (err as Error).message;
      throw err;
    } finally {
      if (client) {
        const duration = Date.now() - start;
        let target = "";
        try {
          const parsed = new URL(url);
          target = `${parsed.hostname}:${parsed.port || (parsed.protocol === "https:" ? "443" : "80")}`;
        } catch {
          target = url;
        }

        const depStatus =
          errorMsg || statusCode >= 400 ? "error" : "ok";

        client.sendEvent("dependency", {
          trace_id: ctx?.traceId,
          span_id: ctx?.spanId,
          dep_type: "http",
          target,
          operation: method,
          url,
          duration_ms: duration,
          status: depStatus,
          status_code: statusCode,
          error_message: errorMsg,
        });
      }
    }
  };
}

export function unpatchHttp(): void {
  if (_originalFetch) {
    globalThis.fetch = _originalFetch;
    _originalFetch = null;
  }
}
