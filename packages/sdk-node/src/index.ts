/**
 * Argus Node.js SDK - Instrumentation for AI-native observability.
 */

import { ArgusClient, type ArgusClientConfig } from "./client";
import {
  getCurrentContext,
  runWithContext,
  startSpan,
  startTrace,
  type TraceContext,
} from "./context";
import {
  buildContext,
  detectRuntime,
  endInvocation,
  startInvocation,
} from "./serverless";

export { ArgusClient, type ArgusClientConfig } from "./client";
export { ArgusLogger } from "./logger";
export { argusMiddleware } from "./middleware/index";
export {
  detectRuntime,
  startInvocation,
  endInvocation,
  getActiveInvocationId,
  type ServerlessContext,
  type ServerlessRuntime,
} from "./serverless";
export {
  getCurrentContext,
  runWithContext,
  startTrace,
  startSpan,
  toTraceparent,
  fromTraceparent,
  type TraceContext,
} from "./context";
export { addBreadcrumb, getBreadcrumbs, clearBreadcrumbs } from "./breadcrumbs";
export { startRuntimeMetrics, stopRuntimeMetrics } from "./runtime";
export { patchHttp, unpatchHttp } from "./integrations/http";
export { ArgusWebhookHandler, type ToolHandler, type ToolResult, type WebhookHandlerOptions } from "./webhook";

export const VERSION = "0.1.0";

// Serverless-tuned defaults
const SERVERLESS_FLUSH_INTERVAL = 1000;
const SERVERLESS_BATCH_SIZE = 10;

let _client: ArgusClient | null = null;

export function init(config: ArgusClientConfig): void {
  const runtime = detectRuntime();

  // Auto-tune for serverless
  const effectiveConfig = { ...config };
  if (runtime) {
    if (!effectiveConfig.flushInterval) {
      effectiveConfig.flushInterval = SERVERLESS_FLUSH_INTERVAL;
    }
    if (!effectiveConfig.batchSize) {
      effectiveConfig.batchSize = SERVERLESS_BATCH_SIZE;
    }
  }

  _client = new ArgusClient(effectiveConfig);

  // Set serverless context if detected
  if (runtime) {
    const ctx = buildContext(runtime);
    if (config.serviceName) {
      ctx.functionName = ctx.functionName || config.serviceName;
    }
    _client.setServerlessContext(ctx);
  }

  // Send deploy event with version info
  const deployData = _detectVersionInfo();
  if (deployData.git_sha || deployData.sdk_version) {
    _client.sendEvent("deploy", {
      service: config.serviceName || "",
      ...deployData,
    });
  }
}

export function getClient(): ArgusClient | null {
  return _client;
}

export function event(name: string, data: Record<string, unknown> = {}): void {
  _client?.sendEvent("event", { name, ...data });
}

export function captureException(err: Error): void {
  const data: Record<string, unknown> = {
    type: err.constructor.name,
    message: err.message,
    stack: err.stack || "",
  };

  // Attach trace context
  const ctx = getCurrentContext();
  if (ctx) {
    data.trace_id = ctx.traceId;
    data.span_id = ctx.spanId;
  }

  // Attach breadcrumbs
  try {
    const { getBreadcrumbs, clearBreadcrumbs } = require("./breadcrumbs");
    const crumbs = getBreadcrumbs();
    if (crumbs.length > 0) {
      data.breadcrumbs = crumbs;
      clearBreadcrumbs();
    }
  } catch {
    // breadcrumbs module not available
  }

  _client?.sendEvent("exception", data);
}

export function trace(name?: string) {
  return function <T extends (...args: unknown[]) => unknown>(
    fn: T,
  ): T {
    const traceName = name || fn.name || "anonymous";

    const wrapped = function (this: unknown, ...args: unknown[]) {
      if (!_client) return fn.apply(this, args);

      const parent = getCurrentContext();
      const ctx = startSpan(parent);

      return runWithContext(ctx, () => {
        const start = Date.now();
        try {
          const result = fn.apply(this, args);
          if (result instanceof Promise) {
            return result
              .then((val: unknown) => {
                _client?.sendEvent("span", {
                  trace_id: ctx.traceId,
                  span_id: ctx.spanId,
                  parent_span_id: ctx.parentSpanId,
                  name: traceName,
                  kind: "internal",
                  duration_ms: Date.now() - start,
                  status: "ok",
                });
                return val;
              })
              .catch((err: Error) => {
                _client?.sendEvent("span", {
                  trace_id: ctx.traceId,
                  span_id: ctx.spanId,
                  parent_span_id: ctx.parentSpanId,
                  name: traceName,
                  kind: "internal",
                  duration_ms: Date.now() - start,
                  status: "error",
                  error_type: err.constructor.name,
                  error_message: err.message,
                });
                throw err;
              });
          }
          _client?.sendEvent("span", {
            trace_id: ctx.traceId,
            span_id: ctx.spanId,
            parent_span_id: ctx.parentSpanId,
            name: traceName,
            kind: "internal",
            duration_ms: Date.now() - start,
            status: "ok",
          });
          return result;
        } catch (err) {
          _client?.sendEvent("span", {
            trace_id: ctx.traceId,
            span_id: ctx.spanId,
            parent_span_id: ctx.parentSpanId,
            name: traceName,
            kind: "internal",
            duration_ms: Date.now() - start,
            status: "error",
            error_type: (err as Error).constructor.name,
            error_message: (err as Error).message,
          });
          throw err;
        }
      });
    } as unknown as T;

    Object.defineProperty(wrapped, "name", { value: traceName });
    return wrapped;
  };
}

export function flushSync(): void {
  _client?.flushSync();
}

export async function shutdown(): Promise<void> {
  if (_client) {
    await _client.close();
    _client = null;
  }
}

function _detectVersionInfo(): Record<string, string> {
  const data: Record<string, string> = { sdk_version: VERSION };

  // Try environment variables for git SHA
  const shaEnvVars = [
    "GIT_SHA",
    "COMMIT_SHA",
    "VERCEL_GIT_COMMIT_SHA",
    "RAILWAY_GIT_COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "HEROKU_SLUG_COMMIT",
  ];
  for (const env of shaEnvVars) {
    const val = process.env[env];
    if (val) {
      data.git_sha = val;
      break;
    }
  }

  // Fallback to git rev-parse
  if (!data.git_sha) {
    try {
      const { execSync } = require("node:child_process");
      data.git_sha = execSync("git rev-parse HEAD", {
        encoding: "utf-8",
        timeout: 2000,
      }).trim();
    } catch {
      // not in a git repo
    }
  }

  // Environment
  data.environment =
    process.env.ENVIRONMENT ||
    process.env.ENV ||
    process.env.NODE_ENV ||
    "";

  return data;
}
