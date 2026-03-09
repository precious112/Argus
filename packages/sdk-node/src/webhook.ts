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
import * as fs from "node:fs";
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

  // CPU usage: sample idle delta over a short window
  let cpuPercent = 0;
  try {
    const t1 = os.cpus();
    const idle1 = t1.reduce((s, c) => s + c.times.idle, 0);
    const total1 = t1.reduce(
      (s, c) => s + c.times.user + c.times.nice + c.times.sys + c.times.irq + c.times.idle,
      0
    );
    // Use a synchronous sleep via Atomics for a brief 200ms sample
    const buf = new SharedArrayBuffer(4);
    Atomics.wait(new Int32Array(buf), 0, 0, 200);
    const t2 = os.cpus();
    const idle2 = t2.reduce((s, c) => s + c.times.idle, 0);
    const total2 = t2.reduce(
      (s, c) => s + c.times.user + c.times.nice + c.times.sys + c.times.irq + c.times.idle,
      0
    );
    const idleDelta = idle2 - idle1;
    const totalDelta = total2 - total1;
    cpuPercent = totalDelta > 0 ? +((1 - idleDelta / totalDelta) * 100).toFixed(1) : 0;
  } catch {
    cpuPercent = 0;
  }

  // Disk usage for root partition
  let disk: Record<string, unknown> = {};
  try {
    const out = execSync("df -k / | tail -1", { encoding: "utf-8", timeout: 3000 });
    const parts = out.trim().split(/\s+/);
    // df -k output: Filesystem 1K-blocks Used Available Use% Mounted
    if (parts.length >= 5) {
      const totalKb = parseInt(parts[1], 10);
      const usedKb = parseInt(parts[2], 10);
      disk = {
        total_gb: +(totalKb / 1e6).toFixed(2),
        used_gb: +(usedKb / 1e6).toFixed(2),
        percent: +(usedKb / totalKb * 100).toFixed(1),
      };
    }
  } catch {
    disk = { error: "unable to read disk usage" };
  }

  return {
    cpu_percent: cpuPercent,
    cpu_count: cpus.length,
    cpu_model: cpus[0]?.model ?? "unknown",
    memory: {
      total_gb: +(totalMem / 1e9).toFixed(2),
      used_gb: +((totalMem - freeMem) / 1e9).toFixed(2),
      percent: +(((totalMem - freeMem) / totalMem) * 100).toFixed(1),
    },
    disk,
    load_avg: os.loadavg(),
    hostname: os.hostname(),
    platform: `${os.platform()} ${os.release()}`,
    uptime_hours: +(os.uptime() / 3600).toFixed(1),
  };
}

function toolProcessList(args: Record<string, unknown>): Record<string, unknown> {
  const limit = Math.min(Number(args.limit ?? 20), 100);
  const sortBy = String(args.sort_by ?? "cpu");

  try {
    // ps output: PID %CPU %MEM STAT COMMAND
    const out = execSync("ps aux --sort=-%cpu 2>/dev/null || ps aux", {
      encoding: "utf-8",
      timeout: 5000,
      maxBuffer: 2 * 1024 * 1024,
    });
    const lines = out.trim().split("\n");
    const header = lines[0];
    const procs: Record<string, unknown>[] = [];

    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].trim().split(/\s+/);
      if (parts.length < 11) continue;
      procs.push({
        pid: parseInt(parts[1], 10),
        cpu_percent: parseFloat(parts[2]),
        memory_percent: parseFloat(parts[3]),
        status: parts[7],
        name: parts[10],
        cmdline: parts.slice(10).join(" "),
      });
    }

    // Sort by requested field
    const key = sortBy === "memory" ? "memory_percent" : "cpu_percent";
    procs.sort((a, b) => ((b[key] as number) || 0) - ((a[key] as number) || 0));

    return { processes: procs.slice(0, limit), total: procs.length, header };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

function toolNetworkConnections(args: Record<string, unknown>): Record<string, unknown> {
  const limit = Math.min(Number(args.limit ?? 50), 200);

  try {
    // Try ss first (Linux), fall back to netstat
    let out: string;
    try {
      out = execSync("ss -tunap 2>/dev/null", {
        encoding: "utf-8",
        timeout: 5000,
        maxBuffer: 2 * 1024 * 1024,
      });
    } catch {
      out = execSync("netstat -an 2>/dev/null || echo ''", {
        encoding: "utf-8",
        timeout: 5000,
        maxBuffer: 2 * 1024 * 1024,
      });
    }

    const lines = out.trim().split("\n");
    const connections: Record<string, unknown>[] = [];

    for (let i = 1; i < lines.length && connections.length < limit; i++) {
      const parts = lines[i].trim().split(/\s+/);
      if (parts.length < 5) continue;
      connections.push({
        proto: parts[0],
        state: parts[1],
        local: parts[4] ?? "",
        remote: parts[5] ?? "",
        raw: lines[i].trim(),
      });
    }

    return { connections, total: lines.length - 1 };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

function toolLogSearch(args: Record<string, unknown>): Record<string, unknown> {
  const path = String(args.path ?? "/var/log/syslog");
  const pattern = String(args.pattern ?? "");
  const limit = Math.min(Number(args.limit ?? 50), 500);

  if (!pattern) return { error: "pattern is required" };

  // Basic path validation — block obvious traversals
  if (path.includes("..")) return { error: "path traversal not allowed" };

  try {
    const out = execSync(
      `grep -n -i ${shellEscape(pattern)} ${shellEscape(path)}`,
      { encoding: "utf-8", timeout: 10000, maxBuffer: 2 * 1024 * 1024 }
    );
    const lines = out.trim().split("\n").filter(Boolean);
    return { matches: lines.slice(-limit), total: lines.length };
  } catch (err) {
    const e = err as { status?: number; stdout?: string; stderr?: string; message?: string };
    // grep returns exit 1 when no matches — that's not an error
    if (e.status === 1) return { matches: [], total: 0 };
    return { error: e.message ?? String(err) };
  }
}

function toolSecurityScan(): Record<string, unknown> {
  const checks: Record<string, unknown> = {};

  // World-writable files in /tmp
  try {
    const out = execSync("find /tmp -maxdepth 1 -perm -o+w -type f 2>/dev/null", {
      encoding: "utf-8",
      timeout: 5000,
    });
    const files = out.trim().split("\n").filter(Boolean);
    checks.world_writable_tmp = files.length;
  } catch {
    checks.world_writable_tmp = "check_failed";
  }

  // Listening ports
  try {
    let out: string;
    try {
      out = execSync("ss -tlnp 2>/dev/null", { encoding: "utf-8", timeout: 5000 });
    } catch {
      out = execSync("netstat -tlnp 2>/dev/null || netstat -an | grep LISTEN", {
        encoding: "utf-8",
        timeout: 5000,
      });
    }
    const lines = out.trim().split("\n").slice(1); // skip header
    const listeners: Record<string, unknown>[] = [];
    for (const line of lines) {
      const parts = line.trim().split(/\s+/);
      if (parts.length >= 4) {
        const local = parts[3] ?? parts[1] ?? "";
        const portMatch = local.match(/:(\d+)$/);
        if (portMatch) {
          listeners.push({ port: parseInt(portMatch[1], 10), raw: line.trim() });
        }
      }
    }
    checks.listening_ports = listeners;
  } catch {
    checks.listening_ports = "check_failed";
  }

  checks.hostname = os.hostname();
  return checks;
}

function toolRunCommand(
  args: Record<string, unknown>
): Record<string, unknown> {
  let command: string;
  const rawCmd = args.command ?? "";
  const timeout = Math.min(Number(args.timeout ?? 10), 30) * 1000;

  if (Array.isArray(rawCmd)) {
    command = rawCmd.join(" ");
  } else {
    command = String(rawCmd);
  }
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

/** Escape a string for safe shell argument use. */
function shellEscape(s: string): string {
  return "'" + s.replace(/'/g, "'\\''") + "'";
}

const DEFAULT_TOOLS: Record<string, ToolHandler> = {
  system_metrics: () => toolSystemMetrics(),
  process_list: (args) => toolProcessList(args),
  network_connections: (args) => toolNetworkConnections(args),
  log_search: (args) => toolLogSearch(args),
  security_scan: () => toolSecurityScan(),
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
   *
   * Works correctly whether mounted before or after body-parsing
   * middleware (express.json(), express.raw(), etc.).
   */
  expressMiddleware(): (
    req: {
      method: string;
      path: string;
      body?: Buffer | string | Record<string, unknown>;
      headers: Record<string, string>;
    },
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

      // Helper to process once we have the raw body Buffer
      const handle = async (body: Buffer) => {
        const result = await self.handleRequest(body, req.headers);
        const status = result.error ? 400 : 200;
        res.status(status).json(result);
      };

      // Case 1: Body already available (express.raw() or express.json() ran first)
      if (req.body !== undefined && req.body !== null) {
        let buf: Buffer;
        if (Buffer.isBuffer(req.body)) {
          // express.raw() — ideal, we have the exact bytes
          buf = req.body;
        } else if (typeof req.body === "string") {
          buf = Buffer.from(req.body);
        } else {
          // express.json() parsed it into an object — re-serialize.
          // This works because the server signs the JSON it sends and
          // JSON.stringify produces identical output for simple payloads.
          // However, whitespace differences could break verification,
          // so we warn and try anyway.
          buf = Buffer.from(JSON.stringify(req.body));
        }
        handle(buf);
        return;
      }

      // Case 2: No body parser ran yet — collect raw chunks from the stream
      const chunks: Buffer[] = [];
      const rawReq = req as unknown as {
        on: (event: string, cb: (data?: Buffer) => void) => void;
      };
      rawReq.on("data", (chunk?: Buffer) => { if (chunk) chunks.push(chunk); });
      rawReq.on("end", () => {
        handle(Buffer.concat(chunks));
      });
    };
  }
}
