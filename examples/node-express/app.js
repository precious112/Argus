/**
 * Example Express application instrumented with Argus Node SDK.
 */

const express = require("express");

// In production these would come from @argus/node
// For local dev, point to the built SDK
let Argus;
try {
  Argus = require("@argus/node");
} catch {
  Argus = {
    init() {},
    event() {},
    captureException() {},
    shutdown() {},
    argusMiddleware() { return (req, res, next) => next(); },
    addBreadcrumb() {},
    startRuntimeMetrics() {},
    patchHttp() {},
    trace(name) { return (fn) => fn; },
  };
}

Argus.init({
  serverUrl: process.env.ARGUS_URL || "http://localhost:7600",
  apiKey: process.env.ARGUS_API_KEY || "",
  serviceName: "example-express",
});

// UC2: Start runtime metrics collection (10s interval for testing)
Argus.startRuntimeMetrics(10000);

// UC3: Patch global fetch for dependency tracking + trace propagation
Argus.patchHttp();

const app = express();
app.use(Argus.argusMiddleware());

app.get("/", (req, res) => {
  res.json({ status: "ok", service: "example-express" });
});

app.get("/users", (req, res) => {
  Argus.event("users_fetched", { count: 3 });
  res.json({
    users: [
      { id: 1, name: "Alice" },
      { id: 2, name: "Bob" },
      { id: 3, name: "Charlie" },
    ],
  });
});

app.post("/error", (req, res) => {
  try {
    throw new Error("Intentional test error");
  } catch (err) {
    Argus.captureException(err);
    res.json({ error: err.message });
  }
});

app.get("/slow", async (req, res) => {
  const delay = Math.random() * 2 + 1;
  await new Promise((r) => setTimeout(r, delay * 1000));
  res.json({ message: "done", delay_seconds: Math.round(delay * 100) / 100 });
});

// --- Phase 1 endpoints ---

app.get("/chain", async (req, res) => {
  // UC1+UC3: Outgoing fetch to self + dependency tracking + trace propagation
  const port = process.env.PORT || 8001;
  try {
    const upstream = await fetch(`http://localhost:${port}/users`);
    const upstreamUsers = await upstream.json();
    res.json({ upstream_users: upstreamUsers });
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
});

app.post("/checkout", async (req, res) => {
  // UC5: Error correlation with trace context + breadcrumbs
  Argus.addBreadcrumb("checkout", "Validating cart contents", { items: 3 });
  await new Promise((r) => setTimeout(r, 10));

  Argus.addBreadcrumb("checkout", "Charging payment", { amount: 99.99, method: "card" });
  await new Promise((r) => setTimeout(r, 10));

  Argus.addBreadcrumb("checkout", "Updating inventory");

  try {
    // Simulate a payment failure
    throw new Error("Payment gateway timeout");
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
});

app.get("/external", async (req, res) => {
  // UC3: Real external dependency tracking via fetch
  try {
    const resp = await fetch("https://jsonplaceholder.typicode.com/todos/1");
    const data = await resp.json();
    res.json({ external_result: data });
  } catch (err) {
    Argus.captureException(err);
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 8001;
app.listen(PORT, () => {
  console.log(`Example Express app listening on port ${PORT}`);
});

process.on("SIGTERM", async () => {
  await Argus.shutdown();
  process.exit(0);
});
