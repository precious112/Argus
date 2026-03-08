/**
 * Argus SDK webhook handler — receives tool execution requests from Argus cloud.
 *
 * Usage with Express:
 *
 *   import { ArgusWebhookHandler } from '@argus/sdk-node';
 *   const handler = new ArgusWebhookHandler({ webhookSecret: 'your-secret' });
 *   app.use(handler.expressMiddleware());
 */

import * as crypto from "node:crypto";
import * as os from "node:os";
import { execSync } from "node:child_process";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ToolResult {
  result: Record<string, unknown> | null;
  error: string | null;
}

export type ToolHandler = (
  args: Record<string, unknown>
) => Record<string, unknown> | Promise<Record<string, unknown>>;

export interface WebhookHandlerOptions {
  webhookSecret: string;
  tools?: Record<string, ToolHandler>;
  /** Route path for the webhook endpoint. Default: /argus/webhook */
  path?: string;
}

// ---------------------------------------------------------------------------
// HMAC verification
// ---------------------------------------------------------------------------

function verifySignature(
  payload: Buffer,
  secret: string,
  signature: string,
  timestamp: string,
  nonce: string,
  maxAge = 300
): boolean {
  const ts = parseInt(timestamp, 10);
  if (isNaN(ts)) return false;
  if (Math.abs(Date.now() / 1000 - ts) > maxAge) return false;

  const message = Buffer.concat([
    Buffer.from(`${timestamp}.${nonce}.`),
    payload,
  ]);
  const expected =
    "sha256=" +
    crypto.createHmac("sha256", secret).update(message).digest("hex");

  try {
    return crypto.timingSafeEqual(
      Buffer.from(expected),
      Buffer.from(signature)
    );
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Built-in host-level tools
// ---------------------------------------------------------------------------

function toolSystemMetrics(): Record<string, unknown> {
  const cpus = os.cpus();
  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  return {
    cpu_count: cpus.length,
    cpu_model: cpus[0]?.model ?? "unknown",
    memory: {
      total_gb: +(totalMem / 1e9).toFixed(2),
      used_gb: +((totalMem - freeMem) / 1e9).toFixed(2),
      percent: +(((totalMem - freeMem) / totalMem) * 100).toFixed(1),
    },
    load_avg: os.loadavg(),
    hostname: os.hostname(),
    platform: `${os.platform()} ${os.release()}`,
    uptime_hours: +(os.uptime() / 3600).toFixed(1),
  };
}

function toolRunCommand(
  args: Record<string, unknown>
): Record<string, unknown> {
  const command = String(args.command ?? "");
  const timeout = Math.min(Number(args.timeout ?? 10), 30) * 1000;
  if (!command) return { error: "command is required" };

  const blocked = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd"];
  for (const b of blocked) {
    if (command.includes(b)) {
      return { error: `Blocked dangerous command pattern: ${b}` };
    }
  }

  try {
    const stdout = execSync(command, {
      timeout,
      encoding: "utf-8",
      maxBuffer: 1024 * 1024,
    });
    return { stdout: stdout.slice(-4096), stderr: "", return_code: 0 };
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string; status?: number; message?: string };
    if (e.stdout !== undefined) {
      return {
        stdout: (e.stdout ?? "").slice(-4096),
        stderr: (e.stderr ?? "").slice(-2048),
        return_code: e.status ?? 1,
      };
    }
    return { error: e.message ?? String(err) };
  }
}

const DEFAULT_TOOLS: Record<string, ToolHandler> = {
  system_metrics: () => toolSystemMetrics(),
  run_command: (args) => toolRunCommand(args),
};

// ---------------------------------------------------------------------------
// Handler class
// ---------------------------------------------------------------------------

export class ArgusWebhookHandler {
  private secret: string;
  private tools: Record<string, ToolHandler>;
  private routePath: string;

  constructor(options: WebhookHandlerOptions) {
    this.secret = options.webhookSecret;
    this.tools = options.tools ?? { ...DEFAULT_TOOLS };
    this.routePath = options.path ?? "/argus/webhook";
  }

  /** Verify signature and execute requested tool. */
  async handleRequest(
    body: Buffer,
    headers: Record<string, string>
  ): Promise<ToolResult> {
    const sig = headers["x-argus-signature"] ?? "";
    const ts = headers["x-argus-timestamp"] ?? "";
    const nonce = headers["x-argus-nonce"] ?? "";

    if (!verifySignature(body, this.secret, sig, ts, nonce)) {
      return { error: "Invalid signature", result: null };
    }

    const payload = JSON.parse(body.toString()) as {
      type?: string;
      tool_name?: string;
      arguments?: Record<string, unknown>;
    };

    if (payload.type === "ping") {
      return { result: { status: "ok" }, error: null };
    }

    if (payload.type !== "tool_execution") {
      return { error: `Unknown request type: ${payload.type}`, result: null };
    }

    const toolName = payload.tool_name ?? "";
    const toolFn = this.tools[toolName];
    if (!toolFn) {
      return { error: `Unknown tool: ${toolName}`, result: null };
    }

    try {
      const result = await toolFn(payload.arguments ?? {});
      return { result, error: null };
    } catch (err) {
      return {
        error: err instanceof Error ? err.message : String(err),
        result: null,
      };
    }
  }

  /**
   * Return an Express-compatible middleware that handles
   * POST requests to the configured path.
   */
  expressMiddleware(): (
    req: { method: string; path: string; body?: unknown; headers: Record<string, string> },
    res: { status: (code: number) => { json: (data: unknown) => void } },
    next: () => void
  ) => void {
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    const self = this;
    const path = this.routePath;

    return (req, res, next) => {
      if (req.method !== "POST" || req.path !== path) {
        return next();
      }

      // Collect raw body
      const chunks: Buffer[] = [];
      const rawReq = req as unknown as {
        on: (event: string, cb: (data?: Buffer) => void) => void;
      };
      rawReq.on("data", (chunk: Buffer) => chunks.push(chunk));
      rawReq.on("end", async () => {
        const body = Buffer.concat(chunks);
        const result = await self.handleRequest(body, req.headers);
        const status = result.error ? 400 : 200;
        res.status(status).json(result);
      });
    };
  }
}
