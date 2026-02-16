/**
 * Database auto-instrumentation for pg (node-postgres).
 */

import { getClient } from "../index";
import { getCurrentContext } from "../context";

let _originalQuery: ((...args: unknown[]) => unknown) | null = null;
let _pgClient: { prototype: { query: (...args: unknown[]) => unknown } } | null = null;

export function patchPg(): void {
  if (_originalQuery) return;

  try {
    const pg = require("pg");
    _pgClient = pg.Client;
    _originalQuery = pg.Client.prototype.query;

    pg.Client.prototype.query = function patchedQuery(
      this: unknown,
      ...args: unknown[]
    ): unknown {
      const client = getClient();
      const start = Date.now();

      // Extract query text
      let queryText = "";
      if (typeof args[0] === "string") {
        queryText = args[0];
      } else if (args[0] && typeof args[0] === "object" && "text" in (args[0] as Record<string, unknown>)) {
        queryText = String((args[0] as Record<string, unknown>).text);
      }

      const operation = queryText.trim().split(/\s+/)[0]?.toUpperCase() || "UNKNOWN";

      const result = _originalQuery!.apply(this, args);

      // Handle promise-based queries
      if (result && typeof (result as Promise<unknown>).then === "function") {
        return (result as Promise<unknown>)
          .then((val: unknown) => {
            if (client) {
              const ctx = getCurrentContext();
              client.sendEvent("dependency", {
                trace_id: ctx?.traceId,
                span_id: ctx?.spanId,
                dep_type: "db",
                target: "postgres",
                operation,
                duration_ms: Date.now() - start,
                status: "ok",
              });
            }
            return val;
          })
          .catch((err: Error) => {
            if (client) {
              const ctx = getCurrentContext();
              client.sendEvent("dependency", {
                trace_id: ctx?.traceId,
                span_id: ctx?.spanId,
                dep_type: "db",
                target: "postgres",
                operation,
                duration_ms: Date.now() - start,
                status: "error",
                error_message: err.message,
              });
            }
            throw err;
          });
      }

      return result;
    };
  } catch {
    // pg not installed
  }
}

export function unpatchPg(): void {
  if (_originalQuery && _pgClient) {
    _pgClient.prototype.query = _originalQuery;
    _originalQuery = null;
    _pgClient = null;
  }
}
