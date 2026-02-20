/**
 * Async-safe trace context propagation using AsyncLocalStorage.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes, randomUUID } from "node:crypto";

export interface TraceContext {
  traceId: string;
  spanId: string;
  parentSpanId?: string;
  baggage: Record<string, string>;
}

const storage = new AsyncLocalStorage<TraceContext>();

function generateTraceId(): string {
  return randomUUID().replace(/-/g, "");
}

function generateSpanId(): string {
  return randomBytes(8).toString("hex");
}

export function toTraceparent(ctx: TraceContext): string {
  return `00-${ctx.traceId}-${ctx.spanId}-01`;
}

export function fromTraceparent(header: string): TraceContext | null {
  const parts = header.trim().split("-");
  if (parts.length < 4) return null;
  return {
    traceId: parts[1],
    spanId: parts[2],
    baggage: {},
  };
}

export function startTrace(
  baggage: Record<string, string> = {},
): TraceContext {
  return {
    traceId: generateTraceId(),
    spanId: generateSpanId(),
    baggage,
  };
}

export function startSpan(parent?: TraceContext | null): TraceContext {
  const p = parent ?? getCurrentContext();
  if (!p) return startTrace();
  return {
    traceId: p.traceId,
    spanId: generateSpanId(),
    parentSpanId: p.spanId,
    baggage: { ...p.baggage },
  };
}

export function getCurrentContext(): TraceContext | undefined {
  return storage.getStore();
}

export function runWithContext<T>(ctx: TraceContext, fn: () => T): T {
  return storage.run(ctx, fn);
}
