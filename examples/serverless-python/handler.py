"""Example serverless function instrumented with Argus SDK.

Works with AWS Lambda, Vercel Functions, GCP Cloud Functions, etc.
Argus auto-detects the runtime from environment variables.
"""

import argus

# Initialize Argus SDK - point at your Argus instance
argus.init(
    server_url="https://argus.your-server.com",
    service_name="my-api",
)


def handler(event, context):
    """Example serverless handler with Argus instrumentation."""
    # Start tracking this invocation
    argus.start_invocation(
        function_name="handler",
        invocation_id=getattr(context, "aws_request_id", ""),
    )

    try:
        # Your business logic here
        result = process_request(event)

        # End invocation on success
        argus.end_invocation(status="ok")

        # Flush events before the function freezes
        argus.flush_sync()

        return {"statusCode": 200, "body": result}

    except Exception as e:
        # Capture the exception
        argus.capture_exception(e)

        # End invocation with error
        argus.end_invocation(status="error", error=str(e))

        # Flush events before the function freezes
        argus.flush_sync()

        return {"statusCode": 500, "body": str(e)}


def process_request(event):
    """Example business logic."""
    # Send custom events for tracking
    argus.event("request_processed", {
        "path": event.get("path", "/"),
        "method": event.get("httpMethod", "GET"),
    })
    return '{"message": "Hello from Argus!"}'
