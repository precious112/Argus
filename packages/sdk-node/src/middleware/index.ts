/**
 * Express middleware for Argus.
 */

import { getClient } from "../index";
import {
  fromTraceparent,
  getCurrentContext,
  runWithContext,
  startSpan,
  startTrace,
  toTraceparent,
  type TraceContext,
} from "../context";

type NextFunction = (err?: unknown) => void;

interface Request {
  method: string;
  path: string;
  url: string;
  headers: Record<string, string | string[] | undefined>;
}

interface Response {
  statusCode: number;
  on(event: string, cb: () => void): void;
  setHeader(name: string, value: string): void;
}

/**
 * Express middleware that logs requests, propagates trace context, and captures errors.
 */
export function argusMiddleware() {
  return (req: Request, res: Response, next: NextFunction): void => {
    const client = getClient();

    // Parse incoming traceparent or start new trace
    const traceparentHeader =
      (req.headers["traceparent"] as string) || "";
    let ctx: TraceContext;
    if (traceparentHeader) {
      const parsed = fromTraceparent(traceparentHeader);
      ctx = parsed ? startSpan(parsed) : startTrace();
    } else {
      ctx = startTrace();
    }

    // Add breadcrumb
    try {
      const { addBreadcrumb } = require("../breadcrumbs");
      addBreadcrumb("http", `${req.method} ${req.path || req.url}`);
    } catch {
      // breadcrumbs not available
    }

    const start = Date.now();

    res.on("finish", () => {
      const duration = Date.now() - start;
      if (client) {
        const spanStatus = res.statusCode >= 500 ? "error" : "ok";
        client.sendEvent("span", {
          trace_id: ctx.traceId,
          span_id: ctx.spanId,
          parent_span_id: ctx.parentSpanId,
          name: `${req.method} ${req.path || req.url}`,
          kind: "server",
          duration_ms: duration,
          status: spanStatus,
          method: req.method,
          path: req.path || req.url,
          status_code: res.statusCode,
        });
      }
    });

    // Set traceparent response header
    res.setHeader("traceparent", toTraceparent(ctx));

    // Run the rest of the middleware chain within the trace context
    runWithContext(ctx, () => next());
  };
}
