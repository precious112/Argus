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
  Argus = { init() {}, event() {}, captureException() {}, shutdown() {}, argusMiddleware() { return (req, res, next) => next(); } };
}

Argus.init({
  serverUrl: process.env.ARGUS_URL || "http://localhost:7600",
  apiKey: process.env.ARGUS_API_KEY || "",
  serviceName: "example-express",
});

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

const PORT = process.env.PORT || 8001;
app.listen(PORT, () => {
  console.log(`Example Express app listening on port ${PORT}`);
});

process.on("SIGTERM", async () => {
  await Argus.shutdown();
  process.exit(0);
});
