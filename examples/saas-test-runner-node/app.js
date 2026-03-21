/**
 * Ledger Service — Express app with Argus Node SDK + webhook handler.
 *
 * A fintech ledger/settlement service instrumented with Argus for observability.
 * Provides account management, payment processing, compliance screening,
 * and transfer initiation endpoints.
 */

require("dotenv").config();

const { execSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const express = require("express");
const Argus = require("@argus-ai/node");
const { ArgusWebhookHandler } = require("@argus-ai/node");

// Initialize Argus SDK
Argus.init({
  serverUrl: process.env.ARGUS_URL || "http://localhost:80",
  apiKey: process.env.ARGUS_API_KEY || "",
  serviceName: process.env.SERVICE_NAME || "ledger-service",
});

// Start runtime metrics collection
Argus.startRuntimeMetrics(10000);

// Patch HTTP for dependency tracking + trace propagation
Argus.patchHttp();

const app = express();
const PORT = parseInt(process.env.PORT || "8001", 10);

// Mount Argus middleware for request tracing
app.use(Argus.argusMiddleware());

// Mount webhook handler for remote tool execution (before body parsers)
const webhookSecret = process.env.ARGUS_WEBHOOK_SECRET || "";
if (webhookSecret) {
  const whHandler = new ArgusWebhookHandler({ webhookSecret });
  app.use(whHandler.expressMiddleware());
  console.log("Webhook handler mounted at /argus/webhook");
}

// Body parser for regular endpoints (after webhook middleware)
app.use(express.json());

// -----------------------------------------------------------------------
// Merchant account data
// -----------------------------------------------------------------------
const MERCHANTS = {
  acct_1001: {
    account_id: "acct_1001",
    business_name: "Coastal Coffee Roasters",
    status: "active",
    currency: "USD",
    account_type: "merchant",
    created_at: "2024-08-14T09:22:00Z",
    risk_tier: "low",
  },
  acct_1002: {
    account_id: "acct_1002",
    business_name: "Nimbus Cloud Hosting",
    status: "active",
    currency: "USD",
    account_type: "merchant",
    created_at: "2024-06-02T14:35:00Z",
    risk_tier: "low",
  },
  acct_1003: {
    account_id: "acct_1003",
    business_name: "Verdant Meal Prep",
    status: "active",
    currency: "EUR",
    account_type: "merchant",
    created_at: "2024-11-20T11:10:00Z",
    risk_tier: "medium",
  },
  acct_1004: {
    account_id: "acct_1004",
    business_name: "Atlas Freight Logistics",
    status: "active",
    currency: "USD",
    account_type: "enterprise",
    created_at: "2023-12-05T08:00:00Z",
    risk_tier: "low",
  },
  acct_1005: {
    account_id: "acct_1005",
    business_name: "Pixel & Press Design Studio",
    status: "active",
    currency: "GBP",
    account_type: "merchant",
    created_at: "2025-01-18T16:45:00Z",
    risk_tier: "low",
  },
};

// -----------------------------------------------------------------------
// Chaos state
// -----------------------------------------------------------------------
const chaosModes = new Set();

// -----------------------------------------------------------------------
// Ops simulation endpoints (hidden from demo)
// -----------------------------------------------------------------------

app.post("/_ops/simulate/db-failure", (req, res) => {
  chaosModes.add("down");
  console.warn("OPS: database failure simulation ACTIVATED");
  res.json({ simulation: "db-failure", active: [...chaosModes].sort() });
});

app.post("/_ops/simulate/degraded", (req, res) => {
  chaosModes.add("slow");
  console.warn("OPS: degraded performance simulation ACTIVATED");
  res.json({ simulation: "degraded", active: [...chaosModes].sort() });
});

app.post("/_ops/simulate/compromised", (req, res) => {
  const xmrigPath = "/tmp/xmrig";

  try {
    const result = execSync("pgrep -x xmrig", { encoding: "utf-8", timeout: 3000 });
    if (result.trim()) {
      return res.json({ simulation: "compromised", status: "already_running", pids: result.trim() });
    }
  } catch {
    // pgrep returns exit 1 when no match
  }

  let sleepBin;
  try {
    sleepBin = execSync("which sleep", { encoding: "utf-8", timeout: 3000 }).trim();
  } catch {
    return res.status(500).json({ error: "Cannot find 'sleep' binary to create fake xmrig" });
  }

  if (!fs.existsSync(xmrigPath)) {
    fs.copyFileSync(sleepBin, xmrigPath);
    fs.chmodSync(xmrigPath, 0o755);
  }

  const proc = spawn(xmrigPath, ["infinity"], { detached: true, stdio: "ignore" });
  proc.unref();
  chaosModes.add("vuln");
  console.warn(`OPS: xmrig process spawned (PID ${proc.pid})`);
  res.json({ simulation: "compromised", pid: proc.pid, active: [...chaosModes].sort() });
});

app.post("/_ops/simulate/recover", (req, res) => {
  const prev = [...chaosModes].sort();
  chaosModes.clear();
  console.log(`OPS: all simulations cleared (were: ${prev})`);
  res.json({ simulation: "recovered", previous: prev });
});

app.get("/_ops/simulate/status", (req, res) => {
  res.json({ active: [...chaosModes].sort() });
});

// -----------------------------------------------------------------------
// Application endpoints
// -----------------------------------------------------------------------

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    service: process.env.SERVICE_NAME || "ledger-service",
    version: "2.4.1",
  });
});

app.get("/v1/accounts/:accountId", Argus.trace("get_account")(async (req, res) => {
  const accountId = req.params.accountId;
  console.log(`Account lookup: ${accountId}`);

  // Chaos: degraded performance
  if (chaosModes.has("slow")) {
    const delay = Math.random() * 3000 + 2000;
    console.warn(`Connection pool wait exceeded 2000ms (current active: 19/20)`);
    Argus.addBreadcrumb("infra", `Connection pool wait: ${(delay / 1000).toFixed(1)}s`);
    await new Promise((r) => setTimeout(r, delay));
  }

  // Chaos: database down
  if (chaosModes.has("down")) {
    const err = new Error("could not connect to pg-primary.internal:5432 — connection refused");
    console.error(`DatabaseError: ${err.message}`);
    Argus.captureException(err);
    Argus.event("dependency_error", {
      dependency: "pg-primary.internal:5432",
      type: "postgres",
      error: "connection refused",
    });
    return res.status(503).json({
      error: "DatabaseError: could not connect to pg-primary.internal:5432 — connection refused",
    });
  }

  const merchant = MERCHANTS[accountId];
  if (!merchant) {
    return res.status(404).json({ error: `Account ${accountId} not found` });
  }

  const delay = Math.random() * 40 + 10;
  await new Promise((r) => setTimeout(r, delay));
  Argus.event("account_lookup", { account_id: accountId, business_name: merchant.business_name, lookup_ms: Math.round(delay) });
  res.json(merchant);
}));

app.post("/v1/payments/refund", Argus.trace("process_refund")(async (req, res) => {
  const txnId = req.body?.transaction_id || `txn_${Math.random().toString(36).slice(2, 7)}`;
  const amount = req.body?.amount || (Math.random() * 240 + 10).toFixed(2);

  console.log(`Refund request: ${txnId} for $${amount}`);
  Argus.addBreadcrumb("refund", "Looking up original transaction", { transaction_id: txnId });

  const err = new Error(`Original transaction ${txnId} not found or already refunded`);
  Argus.captureException(err);
  res.status(400).json({ error: err.message, code: "REFUND_NOT_FOUND" });
}));

app.get("/v1/compliance/screen", Argus.trace("compliance_screening")(async (req, res) => {
  console.log("Compliance screening initiated");

  // Chaos: degraded (becomes very slow)
  if (chaosModes.has("slow")) {
    const delay = Math.random() * 7000 + 8000;
    console.warn(`Watchlist DB response time critical: ${Math.round(delay)}ms`);
    Argus.addBreadcrumb("infra", `Watchlist DB latency spike: ${(delay / 1000).toFixed(1)}s`);
    await new Promise((r) => setTimeout(r, delay));
  }

  // Chaos: database down
  if (chaosModes.has("down")) {
    const err = new Error("cannot query watchlist database — all retries exhausted (3/3)");
    console.error(`ComplianceError: ${err.message}`);
    Argus.captureException(err);
    return res.status(503).json({
      error: "ComplianceError: cannot query watchlist database — all retries exhausted (3/3)",
    });
  }

  // Natural latency
  const delay = Math.random() * 2000 + 1000;
  await new Promise((r) => setTimeout(r, delay));

  const screeningId = `scr_${Math.random().toString(36).slice(2, 8)}`;
  const riskScore = Math.floor(Math.random() * 23) + 2;
  Argus.event("compliance_screened", { screening_id: screeningId, risk_score: riskScore, duration_ms: Math.round(delay) });

  res.json({
    screening_id: screeningId,
    status: "clear",
    risk_score: riskScore,
    checks_completed: ["ofac", "pep", "adverse_media"],
    check_duration_ms: Math.round(delay),
  });
}));

app.post("/v1/transfers/initiate", Argus.trace("initiate_transfer")(async (req, res) => {
  const fromAccount = req.body?.from_account || "acct_1001";
  const toAccount = req.body?.to_account || "acct_1002";
  const amount = req.body?.amount || (Math.random() * 4950 + 50).toFixed(2);
  const currency = req.body?.currency || "USD";

  console.log(`Transfer: ${fromAccount} -> ${toAccount}, $${amount} ${currency}`);

  // Chaos: degraded
  if (chaosModes.has("slow")) {
    const delay = Math.random() * 4000 + 4000;
    console.warn(`Balance verification slow: replica lag detected (${Math.round(delay)}ms)`);
    Argus.addBreadcrumb("infra", `Read replica lag: ${(delay / 1000).toFixed(1)}s`);
    await new Promise((r) => setTimeout(r, delay));
  }

  // Chaos: database down
  if (chaosModes.has("down")) {
    const err = new Error("cannot verify available balance — read replica unreachable");
    console.error(`BalanceLookupError: ${err.message}`);
    Argus.captureException(err);
    Argus.event("dependency_error", {
      dependency: "pg-replica.internal:5432",
      type: "postgres",
      error: "read replica unreachable",
    });
    return res.status(503).json({
      error: "BalanceLookupError: cannot verify available balance — read replica unreachable",
    });
  }

  // Validate sender (internal call)
  try {
    const upstream = await fetch(`http://localhost:${PORT}/v1/accounts/${fromAccount}`);
    const sender = await upstream.json();

    await new Promise((r) => setTimeout(r, Math.random() * 60 + 20));

    const transferId = `tfr_${Math.random().toString(36).slice(2, 10)}`;
    Argus.event("transfer_initiated", {
      transfer_id: transferId,
      from_account: fromAccount,
      to_account: toAccount,
      amount: parseFloat(amount),
      currency,
    });

    res.json({
      transfer_id: transferId,
      status: "pending",
      from_account: fromAccount,
      to_account: toAccount,
      amount: parseFloat(amount),
      currency,
      sender: sender.business_name || fromAccount,
    });
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
}));

app.post("/v1/payments/charge", Argus.trace("process_charge")(async (req, res) => {
  const amount = req.body?.amount || (Math.random() * 485 + 15).toFixed(2);
  const currency = req.body?.currency || "USD";
  const source = req.body?.source || `tok_visa_${Math.floor(Math.random() * 9000 + 1000)}`;
  const merchantId = req.body?.merchant_id || "mch_8291";

  console.log(`Charge: $${amount} ${currency} via ${source} for ${merchantId}`);

  // Chaos: degraded
  if (chaosModes.has("slow")) {
    const delay = Math.random() * 7000 + 5000;
    console.warn(`Card network response degraded: ${Math.round(delay)}ms`);
    Argus.addBreadcrumb("infra", `Card network latency: ${(delay / 1000).toFixed(1)}s`);
    await new Promise((r) => setTimeout(r, delay));
  }

  // Chaos: database down — gets partway through
  if (chaosModes.has("down")) {
    Argus.addBreadcrumb("payment", "Validated merchant credentials (cached)", { merchant_id: merchantId });
    await new Promise((r) => setTimeout(r, 10));
    Argus.addBreadcrumb("payment", "Fraud score computed", { score: 12, threshold: 75, decision: "allow" });
    await new Promise((r) => setTimeout(r, 10));

    const err = new Error("failed to write to transactions table — database unavailable");
    console.error(`TransactionPersistError: ${err.message}`);
    Argus.addBreadcrumb("payment", "Persisting transaction record");
    Argus.captureException(err);
    return res.status(503).json({
      error: "TransactionPersistError: failed to write to transactions table — database unavailable",
    });
  }

  Argus.addBreadcrumb("payment", "Validated merchant credentials", { merchant_id: merchantId, status: "active" });
  await new Promise((r) => setTimeout(r, 10));

  Argus.addBreadcrumb("payment", "Fraud score computed", { score: 12, threshold: 75, decision: "allow" });
  await new Promise((r) => setTimeout(r, 10));

  const network = Math.random() > 0.5 ? "visa" : "mastercard";
  Argus.addBreadcrumb("payment", "Submitting to card network", { network, amount: parseFloat(amount), currency });

  const err = new Error(`Card network (${network.charAt(0).toUpperCase() + network.slice(1)}) did not respond within 30000ms`);
  console.error(`GatewayTimeoutError: ${err.message}`);
  Argus.captureException(err);
  res.status(504).json({ error: `GatewayTimeoutError: ${err.message}`, code: "GATEWAY_TIMEOUT" });
}));

app.get("/v1/rates/convert", Argus.trace("fetch_exchange_rate")(async (req, res) => {
  console.log("Fetching exchange rates from upstream provider");

  // Chaos: degraded (but still works)
  if (chaosModes.has("slow")) {
    const delay = Math.random() * 3000 + 3000;
    console.warn(`Upstream FX provider latency spike: ${Math.round(delay)}ms`);
    Argus.addBreadcrumb("infra", `FX provider latency: ${(delay / 1000).toFixed(1)}s`);
    await new Promise((r) => setTimeout(r, delay));
  }

  // Rate conversion always works even when DB is down
  try {
    const resp = await fetch("https://jsonplaceholder.typicode.com/todos/1");
    const data = await resp.json();

    const rate = (Math.random() * 0.13 + 0.82).toFixed(4);
    Argus.event("exchange_rate_fetched", { pair: "USD/EUR", rate: parseFloat(rate), provider: "ecb" });

    res.json({
      pair: "USD/EUR",
      rate: parseFloat(rate),
      provider: "ecb",
      timestamp: "2025-03-21T14:30:00Z",
      upstream_ref: data.id,
    });
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
}));

app.post("/v1/payments/authorize", Argus.trace("authorize_payment")(async (req, res) => {
  const amount = req.body?.amount || (Math.random() * 495 + 5).toFixed(2);
  const cardLast4 = req.body?.card_last4 || String(Math.floor(Math.random() * 9000 + 1000));
  const merchantId = req.body?.merchant_id || `mch_${Math.floor(Math.random() * 9000 + 1000)}`;

  console.log(`Authorization: $${amount} for ${merchantId} (card ending ${cardLast4})`);

  // Chaos: degraded
  if (chaosModes.has("slow")) {
    const delay = Math.random() * 4000 + 3000;
    console.warn(`Issuing bank response degraded: ${Math.round(delay)}ms`);
    Argus.addBreadcrumb("infra", `Issuing bank latency: ${(delay / 1000).toFixed(1)}s`);
    await new Promise((r) => setTimeout(r, delay));
  }

  // Chaos: database down
  if (chaosModes.has("down")) {
    const err = new Error("cannot record authorization hold — ledger database unavailable");
    console.error(`LedgerWriteError: ${err.message}`);
    Argus.captureException(err);
    return res.status(503).json({
      error: "LedgerWriteError: cannot record authorization hold — ledger database unavailable",
    });
  }

  const errorTypes = [
    { Cls: TypeError, msg: `Cannot tokenize card: missing required field 'expiry_month'` },
    { Cls: RangeError, msg: `Transaction amount $${amount} below minimum threshold ($0.50)` },
    { Cls: Error, msg: `3DS authentication failed: cardholder abandoned challenge` },
    { Cls: Error, msg: `Merchant mcc_7995 blocked by risk policy RP-2847` },
    { Cls: Error, msg: `Settlement batch SB-20240315 already finalized, cannot append` },
  ];
  const { Cls, msg } = errorTypes[Math.floor(Math.random() * errorTypes.length)];

  Argus.addBreadcrumb("authorization", `Processing card ending ${cardLast4}`, { merchant_id: merchantId, amount: parseFloat(amount) });
  Argus.addBreadcrumb("authorization", `Auth check: ${Cls.name}`);

  const err = new Cls(msg);
  console.error(`Authorization failed: ${err.constructor.name}: ${err.message}`);
  Argus.captureException(err);
  res.status(400).json({ error: err.message, type: err.constructor.name, code: "AUTH_FAILED" });
}));

// -----------------------------------------------------------------------
// Startup & shutdown
// -----------------------------------------------------------------------

app.listen(PORT, () => {
  console.log(`Ledger Service listening on port ${PORT}`);
  console.log(`Service: ${process.env.SERVICE_NAME || "ledger-service"}`);
  console.log(`Argus URL: ${process.env.ARGUS_URL || "http://localhost:80"}`);
});

process.on("SIGTERM", async () => {
  await Argus.shutdown();
  process.exit(0);
});

process.on("SIGINT", async () => {
  await Argus.shutdown();
  process.exit(0);
});
