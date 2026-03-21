#!/usr/bin/env node
/**
 * Ledger Service test runner — generates traffic and error bursts.
 *
 * Run separately from the app. Uses plain HTTP requests (no SDK import).
 * Chaos scenarios are triggered via the app's /_ops/simulate/* endpoints.
 *
 * Usage:
 *   node test_runner.js
 *
 * Environment:
 *   APP_URL — base URL of the test app (default: http://localhost:8001)
 */

require("dotenv").config();

const APP_URL = (process.env.APP_URL || "http://localhost:8001").replace(/\/+$/, "");

const CURRENCIES = ["USD", "EUR", "GBP"];
const MERCHANT_IDS = ["mch_8291", "mch_4517", "mch_7203", "mch_1089", "mch_6345"];
const ACCOUNTS = ["acct_1001", "acct_1002", "acct_1003", "acct_1004", "acct_1005"];

// Weighted endpoint list for traffic generation
const ENDPOINTS = [
  { method: "GET",  path: "/health",               weight: 8 },
  { method: "GET",  path: "/v1/accounts/acct_1001", weight: 6 },
  { method: "GET",  path: "/v1/accounts/acct_1002", weight: 4 },
  { method: "POST", path: "/v1/payments/charge",    weight: 5 },
  { method: "POST", path: "/v1/payments/authorize", weight: 4 },
  { method: "POST", path: "/v1/transfers/initiate", weight: 3 },
  { method: "GET",  path: "/v1/rates/convert",      weight: 3 },
  { method: "GET",  path: "/v1/compliance/screen",  weight: 2 },
  { method: "POST", path: "/v1/payments/refund",    weight: 2 },
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

function randomChoice(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function makeBody(path) {
  if (path === "/v1/payments/charge") {
    return {
      amount: parseFloat((Math.random() * 485 + 15).toFixed(2)),
      currency: randomChoice(CURRENCIES),
      source: `tok_visa_${Math.floor(Math.random() * 9000 + 1000)}`,
      merchant_id: randomChoice(MERCHANT_IDS),
      idempotency_key: `idem_${Math.random().toString(36).slice(2, 10)}`,
    };
  }
  if (path === "/v1/payments/authorize") {
    return {
      amount: parseFloat((Math.random() * 495 + 5).toFixed(2)),
      currency: randomChoice(CURRENCIES),
      card_last4: String(Math.floor(Math.random() * 9000 + 1000)),
      merchant_id: randomChoice(MERCHANT_IDS),
    };
  }
  if (path === "/v1/transfers/initiate") {
    const accts = [...ACCOUNTS].sort(() => Math.random() - 0.5).slice(0, 2);
    return {
      from_account: accts[0],
      to_account: accts[1],
      amount: parseFloat((Math.random() * 4950 + 50).toFixed(2)),
      currency: randomChoice(CURRENCIES),
    };
  }
  if (path === "/v1/payments/refund") {
    return {
      transaction_id: `txn_${Math.random().toString(36).slice(2, 8)}`,
      amount: parseFloat((Math.random() * 240 + 10).toFixed(2)),
      reason: randomChoice(["customer_request", "duplicate", "fraudulent"]),
    };
  }
  return null;
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
      const opts = { method, signal: AbortSignal.timeout(30000) };
      if (method === "POST") {
        const body = makeBody(p);
        if (body) {
          opts.headers = { "Content-Type": "application/json" };
          opts.body = JSON.stringify(body);
        }
      }
      const resp = await fetch(url, opts);
      log("INFO", `${method} ${p} -> ${resp.status}`);
    } catch (err) {
      log("WARN", `${method} ${p} -> error: ${err.message}`);
    }

    const delay = Math.random() * 10000 + 10000; // 10-20s
    await new Promise((r) => setTimeout(r, delay));
  }
}

// -----------------------------------------------------------------------
// Error burst loop — rapid failed authorizations/refunds every ~5 minutes
// -----------------------------------------------------------------------

async function errorBurstLoop() {
  log("INFO", "Error burst loop started");
  // Wait before first burst
  await new Promise((r) => setTimeout(r, 60000));

  while (true) {
    log("INFO", "=== Starting error burst (20 requests) ===");

    for (let i = 0; i < 20; i++) {
      const isRefund = i % 3 === 0;
      const endpoint = isRefund ? "/v1/payments/refund" : "/v1/payments/authorize";
      const body = makeBody(endpoint);

      try {
        await fetch(`${APP_URL}${endpoint}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(30000),
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
// Main
// -----------------------------------------------------------------------

async function main() {
  log("INFO", "============================================================");
  log("INFO", "Ledger Service — Test Runner");
  log("INFO", `Target app: ${APP_URL}`);
  log("INFO", "============================================================");

  // Verify app is reachable
  try {
    const resp = await fetch(`${APP_URL}/health`, { signal: AbortSignal.timeout(5000) });
    const data = await resp.json();
    log("INFO", `App health check: ${resp.status} ${JSON.stringify(data)}`);
  } catch (err) {
    log("ERROR", `Cannot reach app at ${APP_URL}: ${err.message}`);
    log("ERROR", "Start the app first: node app.js");
    process.exit(1);
  }

  // Run traffic and error burst loops concurrently
  log("INFO", "Starting traffic generation...");
  await Promise.all([trafficLoop(), errorBurstLoop()]);
}

main().catch((err) => {
  log("ERROR", `Fatal: ${err.message}`);
  process.exit(1);
});
