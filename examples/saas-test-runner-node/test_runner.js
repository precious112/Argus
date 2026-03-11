#!/usr/bin/env node
/**
 * SaaS test runner — generates traffic, error bursts, and a fake xmrig process.
 *
 * Run separately from the app. Uses plain HTTP requests (no SDK import).
 *
 * Usage:
 *   node test_runner.js
 *
 * Environment:
 *   APP_URL — base URL of the test app (default: http://localhost:8001)
 */

require("dotenv").config();

const { execSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const APP_URL = (process.env.APP_URL || "http://localhost:8001").replace(/\/+$/, "");

// Weighted endpoint list for traffic generation
const ENDPOINTS = [
  { method: "GET", path: "/", weight: 10 },
  { method: "GET", path: "/users/1", weight: 6 },
  { method: "GET", path: "/users/2", weight: 4 },
  { method: "GET", path: "/chain", weight: 3 },
  { method: "GET", path: "/external", weight: 2 },
  { method: "GET", path: "/slow", weight: 2 },
  { method: "POST", path: "/checkout", weight: 2 },
  { method: "POST", path: "/multi-error", weight: 2 },
  { method: "POST", path: "/error", weight: 1 },
];

function buildWeightedList() {
  const weighted = [];
  for (const { method, path: p, weight } of ENDPOINTS) {
    for (let i = 0; i < weight; i++) weighted.push({ method, path: p });
  }
  return weighted;
}

const WEIGHTED = buildWeightedList();

function log(level, msg, ...args) {
  const ts = new Date().toISOString();
  const formatted = args.length ? `${msg} ${args.join(" ")}` : msg;
  console.log(`${ts} [${level}] test_runner: ${formatted}`);
}

// -----------------------------------------------------------------------
// Traffic loop — weighted random requests every ~15s
// -----------------------------------------------------------------------

async function trafficLoop() {
  log("INFO", `Traffic loop started (target: ${APP_URL})`);

  while (true) {
    const { method, path: p } = WEIGHTED[Math.floor(Math.random() * WEIGHTED.length)];
    const url = `${APP_URL}${p}`;

    try {
      const resp = await fetch(url, { method, signal: AbortSignal.timeout(15000) });
      log("INFO", `${method} ${p} -> ${resp.status}`);
    } catch (err) {
      log("WARN", `${method} ${p} -> error: ${err.message}`);
    }

    const delay = Math.random() * 10000 + 10000; // 10-20s
    await new Promise((r) => setTimeout(r, delay));
  }
}

// -----------------------------------------------------------------------
// Error burst loop — 20 rapid error requests every ~5 minutes
// -----------------------------------------------------------------------

async function errorBurstLoop() {
  log("INFO", "Error burst loop started");
  // Wait before first burst
  await new Promise((r) => setTimeout(r, 60000));

  while (true) {
    log("INFO", "=== Starting error burst (20 requests) ===");

    for (let i = 0; i < 20; i++) {
      const endpoint = i % 3 === 0 ? "/multi-error" : "/error";
      try {
        await fetch(`${APP_URL}${endpoint}`, {
          method: "POST",
          signal: AbortSignal.timeout(15000),
        });
      } catch {
        // ignore
      }
      await new Promise((r) => setTimeout(r, 200));
    }

    log("INFO", "=== Error burst complete ===");

    // Wait ~5 minutes before next burst
    const delay = Math.random() * 60000 + 270000; // 270-330s
    await new Promise((r) => setTimeout(r, delay));
  }
}

// -----------------------------------------------------------------------
// Fake xmrig process for security testing
// -----------------------------------------------------------------------

function createXmrigProcess() {
  const xmrigPath = "/tmp/xmrig";

  // Check if already running
  try {
    const result = execSync("pgrep -x xmrig", { encoding: "utf-8", timeout: 3000 });
    if (result.trim()) {
      log("INFO", `xmrig already running (PID ${result.trim()})`);
      return;
    }
  } catch {
    // pgrep returns exit 1 when no match — that's expected
  }

  // Find the sleep binary
  let sleepBin;
  try {
    sleepBin = execSync("which sleep", { encoding: "utf-8", timeout: 3000 }).trim();
  } catch {
    log("ERROR", "Could not find 'sleep' binary — cannot create fake xmrig");
    return;
  }

  // Copy sleep binary as xmrig
  if (!fs.existsSync(xmrigPath)) {
    log("INFO", `Creating fake xmrig at ${xmrigPath} (copy of ${sleepBin})`);
    fs.copyFileSync(sleepBin, xmrigPath);
    fs.chmodSync(xmrigPath, 0o755);
  }

  // Launch it — sleep infinity keeps it alive
  log("INFO", "Starting xmrig process...");
  const proc = spawn(xmrigPath, ["infinity"], {
    detached: true,
    stdio: "ignore",
  });
  proc.unref();
  log("INFO", `xmrig running with PID ${proc.pid}`);
  log("INFO", "To remove: ask Argus chat 'kill the xmrig process'");
}

// -----------------------------------------------------------------------
// Main
// -----------------------------------------------------------------------

async function main() {
  log("INFO", "============================================================");
  log("INFO", "Argus SaaS Test Runner (Node)");
  log("INFO", `Target app: ${APP_URL}`);
  log("INFO", "============================================================");

  // Verify app is reachable
  try {
    const resp = await fetch(`${APP_URL}/`, { signal: AbortSignal.timeout(5000) });
    const data = await resp.json();
    log("INFO", `App health check: ${resp.status} ${JSON.stringify(data)}`);
  } catch (err) {
    log("ERROR", `Cannot reach app at ${APP_URL}: ${err.message}`);
    log("ERROR", "Start the app first: node app.js");
    process.exit(1);
  }

  // Create fake xmrig
  createXmrigProcess();

  // Run traffic and error burst loops concurrently
  log("INFO", "Starting traffic generation...");
  await Promise.all([trafficLoop(), errorBurstLoop()]);
}

main().catch((err) => {
  log("ERROR", `Fatal: ${err.message}`);
  process.exit(1);
});
