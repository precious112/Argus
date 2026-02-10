/**
 * Argus Node.js SDK - Instrumentation for AI-native observability.
 */

import { ArgusClient, type ArgusClientConfig } from "./client";

export { ArgusClient, type ArgusClientConfig } from "./client";
export { ArgusLogger } from "./logger";
export { argusMiddleware } from "./middleware/index";

export const VERSION = "0.1.0";

let _client: ArgusClient | null = null;

export function init(config: ArgusClientConfig): void {
  _client = new ArgusClient(config);
}

export function getClient(): ArgusClient | null {
  return _client;
}

export function event(name: string, data: Record<string, unknown> = {}): void {
  _client?.sendEvent("event", { name, ...data });
}

export function captureException(err: Error): void {
  _client?.sendEvent("exception", {
    type: err.constructor.name,
    message: err.message,
    stack: err.stack || "",
  });
}

export function trace(name?: string) {
  return function <T extends (...args: unknown[]) => unknown>(
    fn: T,
  ): T {
    const traceName = name || fn.name || "anonymous";

    const wrapped = function (this: unknown, ...args: unknown[]) {
      _client?.sendEvent("trace_start", { name: traceName });
      const start = Date.now();
      try {
        const result = fn.apply(this, args);
        if (result instanceof Promise) {
          return result
            .then((val: unknown) => {
              _client?.sendEvent("trace_end", {
                name: traceName,
                duration_ms: Date.now() - start,
              });
              return val;
            })
            .catch((err: Error) => {
              _client?.sendEvent("trace_end", {
                name: traceName,
                duration_ms: Date.now() - start,
                error: err.message,
                error_type: err.constructor.name,
              });
              throw err;
            });
        }
        _client?.sendEvent("trace_end", {
          name: traceName,
          duration_ms: Date.now() - start,
        });
        return result;
      } catch (err) {
        _client?.sendEvent("trace_end", {
          name: traceName,
          duration_ms: Date.now() - start,
          error: (err as Error).message,
          error_type: (err as Error).constructor.name,
        });
        throw err;
      }
    } as unknown as T;

    Object.defineProperty(wrapped, "name", { value: traceName });
    return wrapped;
  };
}

export async function shutdown(): Promise<void> {
  if (_client) {
    await _client.close();
    _client = null;
  }
}
