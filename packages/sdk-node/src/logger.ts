/**
 * Console wrapper / standalone logger for Argus.
 */

import { getClient } from "./index";

export class ArgusLogger {
  private name: string;

  constructor(name = "app") {
    this.name = name;
  }

  log(message: string, data?: Record<string, unknown>): void {
    this._send("INFO", message, data);
    console.log(`[${this.name}] ${message}`);
  }

  warn(message: string, data?: Record<string, unknown>): void {
    this._send("WARNING", message, data);
    console.warn(`[${this.name}] ${message}`);
  }

  error(message: string, data?: Record<string, unknown>): void {
    this._send("ERROR", message, data);
    console.error(`[${this.name}] ${message}`);
  }

  debug(message: string, data?: Record<string, unknown>): void {
    this._send("DEBUG", message, data);
    console.debug(`[${this.name}] ${message}`);
  }

  private _send(
    level: string,
    message: string,
    data?: Record<string, unknown>,
  ): void {
    const client = getClient();
    if (!client) return;
    client.sendEvent("log", {
      level,
      message,
      logger: this.name,
      ...(data || {}),
    });
  }
}

/**
 * Patch global console to also send logs to Argus.
 */
export function patchConsole(): void {
  const origLog = console.log;
  const origWarn = console.warn;
  const origError = console.error;

  console.log = (...args: unknown[]) => {
    const client = getClient();
    if (client) {
      client.sendEvent("log", { level: "INFO", message: args.map(String).join(" ") });
    }
    origLog.apply(console, args);
  };

  console.warn = (...args: unknown[]) => {
    const client = getClient();
    if (client) {
      client.sendEvent("log", { level: "WARNING", message: args.map(String).join(" ") });
    }
    origWarn.apply(console, args);
  };

  console.error = (...args: unknown[]) => {
    const client = getClient();
    if (client) {
      client.sendEvent("log", { level: "ERROR", message: args.map(String).join(" ") });
    }
    origError.apply(console, args);
  };
}
