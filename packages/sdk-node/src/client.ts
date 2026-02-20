/**
 * HTTP client for pushing telemetry to Argus agent.
 */

import type { ServerlessContext } from "./serverless";

export interface ArgusClientConfig {
  serverUrl: string;
  apiKey?: string;
  serviceName?: string;
  flushInterval?: number; // ms, default 5000
  batchSize?: number; // default 100
}

interface TelemetryEvent {
  type: string;
  service: string;
  data: Record<string, unknown>;
}

export class ArgusClient {
  private serverUrl: string;
  private apiKey: string;
  private serviceName: string;
  private batchSize: number;
  private buffer: TelemetryEvent[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private closed = false;
  private serverlessContext: ServerlessContext | null = null;

  constructor(config: ArgusClientConfig) {
    this.serverUrl = config.serverUrl.replace(/\/$/, "");
    this.apiKey = config.apiKey || "";
    this.serviceName = config.serviceName || "";
    this.batchSize = config.batchSize || 100;

    const interval = config.flushInterval || 5000;
    this.timer = setInterval(() => this.flush(), interval);
  }

  setServerlessContext(ctx: ServerlessContext): void {
    this.serverlessContext = ctx;
  }

  sendEvent(type: string, data: Record<string, unknown> = {}): void {
    if (this.closed) return;

    const enrichedData = { ...data };

    // Enrich with serverless context
    if (this.serverlessContext) {
      const { contextToData } = require("./serverless");
      const ctxData = contextToData(this.serverlessContext);
      for (const [k, v] of Object.entries(ctxData)) {
        if (!(k in enrichedData)) {
          enrichedData[k] = v;
        }
      }
    }

    // Enrich with active invocation ID
    try {
      const { getActiveInvocationId } = require("./serverless");
      const invId = getActiveInvocationId();
      if (invId && !("invocation_id" in enrichedData)) {
        enrichedData.invocation_id = invId;
      }
    } catch {
      // serverless module not available
    }

    // Auto-attach trace context if not already present
    try {
      const { getCurrentContext } = require("./context");
      const ctx = getCurrentContext();
      if (ctx) {
        if (!("trace_id" in enrichedData)) enrichedData.trace_id = ctx.traceId;
        if (!("span_id" in enrichedData)) enrichedData.span_id = ctx.spanId;
      }
    } catch {
      // context module not available
    }

    this.buffer.push({
      type,
      service: this.serviceName,
      data: enrichedData,
    });
    if (this.buffer.length >= this.batchSize) {
      this.flush();
    }
  }

  async flush(): Promise<void> {
    if (this.buffer.length === 0) return;

    const events = this.buffer.splice(0, this.batchSize);
    const url = `${this.serverUrl}/api/v1/ingest`;
    const body = JSON.stringify({
      events,
      sdk: "argus-node/0.1.0",
      service: this.serviceName,
    });

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.apiKey) {
      headers["x-argus-key"] = this.apiKey;
    }

    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers,
          body,
          signal: AbortSignal.timeout(10000),
        });
        if (resp.ok) return;
      } catch {
        if (attempt < 2) {
          await new Promise((r) => setTimeout(r, Math.pow(2, attempt) * 1000));
        }
      }
    }
  }

  flushSync(): void {
    // In Node.js we can't truly block, but we trigger the flush
    this.flush();
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    if (this.timer) clearInterval(this.timer);
    await this.flush();
  }
}
