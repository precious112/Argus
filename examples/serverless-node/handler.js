/**
 * Example serverless function instrumented with Argus SDK.
 *
 * Works with AWS Lambda, Vercel Functions, GCP Cloud Functions, etc.
 * Argus auto-detects the runtime from environment variables.
 */

const argus = require("argus-node");

// Initialize Argus SDK - point at your Argus instance
argus.init({
  serverUrl: "https://argus.your-server.com",
  serviceName: "my-api-node",
});

exports.handler = async (event, context) => {
  // Start tracking this invocation
  argus.startInvocation("handler", context?.awsRequestId || "");

  try {
    // Your business logic here
    const result = processRequest(event);

    // End invocation on success
    argus.endInvocation("ok");

    // Flush events before the function freezes
    argus.flushSync();

    return { statusCode: 200, body: result };
  } catch (err) {
    // Capture the exception
    argus.captureException(err);

    // End invocation with error
    argus.endInvocation("error", err.message);

    // Flush events before the function freezes
    argus.flushSync();

    return { statusCode: 500, body: err.message };
  }
};

function processRequest(event) {
  // Send custom events for tracking
  argus.event("request_processed", {
    path: event.path || "/",
    method: event.httpMethod || "GET",
  });

  return JSON.stringify({ message: "Hello from Argus!" });
}
