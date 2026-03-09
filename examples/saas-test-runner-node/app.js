/**
 * SaaS test runner — Express app with Argus Node SDK + webhook handler.
 *
 * Runs on the tenant's VM. Provides:
 * - SDK telemetry (traces, errors, metrics) sent to Argus SaaS
 * - Webhook handler for remote tool execution from Argus SaaS
 * - Test endpoints that generate various types of telemetry
 */

require("dotenv").config();

const express = require("express");
const Argus = require("@argus-ai/node");
const { ArgusWebhookHandler } = require("@argus-ai/node");

// Initialize Argus SDK
Argus.init({
  serverUrl: process.env.ARGUS_URL || "http://localhost:80",
  apiKey: process.env.ARGUS_API_KEY || "",
  serviceName: process.env.SERVICE_NAME || "saas-demo-node",
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
// Endpoints — mirrors the Python saas-test-runner
// -----------------------------------------------------------------------

app.get("/", (req, res) => {
  res.json({ status: "ok", service: process.env.SERVICE_NAME || "saas-demo-node" });
});

app.get("/users/:userId", Argus.trace("get_user")((req, res) => {
  const userId = parseInt(req.params.userId, 10);
  Argus.event("user_fetched", { user_id: userId });
  // Simulate small latency
  const delay = Math.random() * 90 + 10;
  setTimeout(() => {
    res.json({ id: userId, name: `User-${userId}`, email: `user${userId}@example.com` });
  }, delay);
}));

app.post("/error", (req, res) => {
  try {
    // Intentional error for exception capture testing
    const x = 1;
    // eslint-disable-next-line no-unused-vars
    const y = x / 0; // Infinity in JS, so throw explicitly
    throw new Error("Division by zero");
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
});

app.get("/slow", Argus.trace("slow_endpoint")(async (req, res) => {
  const delay = Math.random() * 2 + 1; // 1-3 seconds
  await new Promise((r) => setTimeout(r, delay * 1000));
  res.json({ message: "done", delay_seconds: Math.round(delay * 100) / 100 });
}));

app.get("/chain", Argus.trace("chain_handler")(async (req, res) => {
  try {
    const upstream = await fetch(`http://localhost:${PORT}/users/1`);
    const upstreamData = await upstream.json();

    // Simulate internal processing
    await new Promise((r) => setTimeout(r, Math.random() * 60 + 20));

    res.json({ upstream: upstreamData, internal: "ok" });
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
}));

app.post("/checkout", Argus.trace("checkout_handler")(async (req, res) => {
  Argus.addBreadcrumb("checkout", "Validating cart contents", { items: 3 });
  await new Promise((r) => setTimeout(r, 10));

  Argus.addBreadcrumb("checkout", "Charging payment", { amount: 99.99, method: "card" });
  await new Promise((r) => setTimeout(r, 10));

  Argus.addBreadcrumb("checkout", "Updating inventory");

  try {
    throw new Error("Payment gateway timeout");
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
}));

app.get("/external", Argus.trace("external_call")(async (req, res) => {
  try {
    const resp = await fetch("https://jsonplaceholder.typicode.com/todos/1");
    const data = await resp.json();
    res.json({ external_result: data });
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
}));

app.post("/multi-error", Argus.trace("multi_error_handler")((req, res) => {
  const errorTypes = [
    { Cls: TypeError, msg: "Cannot read property 'id' of undefined" },
    { Cls: RangeError, msg: "Maximum call stack size exceeded" },
    { Cls: URIError, msg: "URI malformed: invalid redirect URL" },
    { Cls: SyntaxError, msg: "Unexpected token in JSON at position 0" },
    { Cls: Error, msg: "Worker process crashed unexpectedly" },
  ];
  const { Cls, msg } = errorTypes[Math.floor(Math.random() * errorTypes.length)];
  Argus.addBreadcrumb("multi-error", `Selected error type: ${Cls.name}`);
  Argus.addBreadcrumb("multi-error", "Simulating failure scenario");

  try {
    throw new Cls(msg);
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message, type: err.constructor.name });
  }
}));

// -----------------------------------------------------------------------
// Startup & shutdown
// -----------------------------------------------------------------------

app.listen(PORT, () => {
  console.log(`Argus SaaS Test App (Node) listening on port ${PORT}`);
  console.log(`Service: ${process.env.SERVICE_NAME || "saas-demo-node"}`);
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
