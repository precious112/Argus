/**
 * Serverless runtime detection and invocation lifecycle helpers.
 */

import { getClient } from "./index";

export type ServerlessRuntime =
  | "aws_lambda"
  | "vercel"
  | "gcp_functions"
  | "cloudflare_workers"
  | null;

export interface ServerlessContext {
  runtime: string;
  functionName: string;
  region: string;
  memoryLimitMb: number;
  invocationId: string;
  isColdStart: boolean;
  deploymentId: string;
}

// Module-level cold start detection
let _initialized = false;

// Active invocation tracking
let _activeInvocation: {
  invocationId: string;
  functionName: string;
  startTime: number;
} | null = null;

export function detectRuntime(): ServerlessRuntime {
  if (process.env.AWS_LAMBDA_FUNCTION_NAME) return "aws_lambda";
  if (process.env.VERCEL) return "vercel";
  if (process.env.FUNCTION_TARGET || process.env.K_SERVICE)
    return "gcp_functions";
  if (process.env.CF_PAGES || process.env.WORKERS_RS_VERSION)
    return "cloudflare_workers";
  return null;
}

export function buildContext(runtime: string): ServerlessContext {
  const isColdStart = !_initialized;
  _initialized = true;

  const ctx: ServerlessContext = {
    runtime,
    functionName: "",
    region: "",
    memoryLimitMb: 0,
    invocationId: "",
    isColdStart,
    deploymentId: "",
  };

  if (runtime === "aws_lambda") {
    ctx.functionName = process.env.AWS_LAMBDA_FUNCTION_NAME || "";
    ctx.region = process.env.AWS_REGION || "";
    ctx.memoryLimitMb = parseInt(
      process.env.AWS_LAMBDA_FUNCTION_MEMORY_SIZE || "0",
      10,
    );
    ctx.deploymentId = process.env.AWS_LAMBDA_FUNCTION_VERSION || "";
  } else if (runtime === "vercel") {
    ctx.functionName = process.env.VERCEL_URL || "";
    ctx.region = process.env.VERCEL_REGION || "";
    ctx.deploymentId =
      process.env.VERCEL_DEPLOYMENT_ID ||
      process.env.VERCEL_GIT_COMMIT_SHA ||
      "";
  } else if (runtime === "gcp_functions") {
    ctx.functionName =
      process.env.FUNCTION_TARGET || process.env.K_SERVICE || "";
    ctx.region = process.env.FUNCTION_REGION || "";
    ctx.memoryLimitMb = parseInt(
      process.env.FUNCTION_MEMORY_MB || "0",
      10,
    );
    ctx.deploymentId = process.env.K_REVISION || "";
  } else if (runtime === "cloudflare_workers") {
    ctx.functionName = process.env.CF_PAGES_BRANCH || "worker";
  }

  return ctx;
}

function contextToData(ctx: ServerlessContext): Record<string, unknown> {
  const data: Record<string, unknown> = {
    runtime: ctx.runtime,
    function_name: ctx.functionName,
    is_cold_start: ctx.isColdStart,
  };
  if (ctx.region) data.region = ctx.region;
  if (ctx.memoryLimitMb) data.memory_limit_mb = ctx.memoryLimitMb;
  if (ctx.invocationId) data.invocation_id = ctx.invocationId;
  if (ctx.deploymentId) data.deployment_id = ctx.deploymentId;
  return data;
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function startInvocation(
  functionName = "",
  invocationId = "",
): string {
  const id = invocationId || generateId();
  _activeInvocation = {
    invocationId: id,
    functionName,
    startTime: performance.now(),
  };

  const client = getClient();
  if (client) {
    const data: Record<string, unknown> = {
      invocation_id: id,
      function_name: functionName,
    };
    // Serverless context is enriched by the client
    client.sendEvent("invocation_start", data);
  }

  return id;
}

export function endInvocation(
  status = "ok",
  error = "",
): void {
  if (!_activeInvocation) return;

  const durationMs = performance.now() - _activeInvocation.startTime;
  const client = getClient();

  if (client) {
    const data: Record<string, unknown> = {
      invocation_id: _activeInvocation.invocationId,
      function_name: _activeInvocation.functionName,
      duration_ms: Math.round(durationMs * 100) / 100,
      status,
    };
    if (error) data.error = error;
    client.sendEvent("invocation_end", data);
  }

  _activeInvocation = null;
}

export function getActiveInvocationId(): string | null {
  return _activeInvocation?.invocationId ?? null;
}

export { contextToData };
