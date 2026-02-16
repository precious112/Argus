/**
 * Example serverless function instrumented with Argus SDK.
 *
 * Works with AWS Lambda, Vercel Functions, GCP Cloud Functions, etc.
 * Argus auto-detects the runtime from environment variables.
 */

const argus = require("argus-node");

// Initialize Argus SDK
argus.init({
  serverUrl: process.env.ARGUS_URL || "https://argus.your-server.com",
  apiKey: process.env.ARGUS_API_KEY || "",
  serviceName: "my-api-node",
});

// Patch HTTP for dependency tracking
argus.patchHttp();

exports.handler = async (event, context) => {
  // Start tracking this invocation
  argus.startInvocation("handler", context?.awsRequestId || "");

  try {
    const result = processRequest(event);

    argus.endInvocation("ok");
    argus.flushSync();

    return { statusCode: 200, body: result };
  } catch (err) {
    argus.captureException(err);
    argus.endInvocation("error", err.message);
    argus.flushSync();

    return { statusCode: 500, body: err.message };
  }
};

function processRequest(event) {
  const path = event.path || "/";
  const method = event.httpMethod || "GET";

  argus.addBreadcrumb("request", "Parsing event", { path, method });

  // Send custom events for tracking
  argus.event("request_processed", { path, method });

  argus.addBreadcrumb("request", "Business logic complete");

  return JSON.stringify({ message: "Hello from Argus!" });
}

exports.errorHandler = async (event, context) => {
  argus.startInvocation("errorHandler", context?.awsRequestId || "");

  argus.addBreadcrumb("error_handler", "Invocation started", {
    function: "errorHandler",
    path: event.path || "/",
  });

  try {
    argus.addBreadcrumb("error_handler", "Validating input");
    // Simulate a validation failure
    throw new Error("Missing required field: user_id");
  } catch (err) {
    argus.addBreadcrumb("error_handler", "Exception caught", { error: err.message });
    argus.captureException(err);
    argus.endInvocation("error", err.message);
    argus.flushSync();

    return { statusCode: 500, body: err.message };
  }
};
