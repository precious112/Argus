"""Example serverless function instrumented with Argus SDK.

Works with AWS Lambda, Vercel Functions, GCP Cloud Functions, etc.
Argus auto-detects the runtime from environment variables.
"""

import logging
import os

import argus
from argus.decorators import trace
from argus.logger import ArgusHandler

# Initialize Argus SDK
argus.init(
    server_url=os.getenv("ARGUS_URL", "https://argus.your-server.com"),
    api_key=os.getenv("ARGUS_API_KEY", ""),
    service_name="my-api",
)

# Add Argus log handler
logging.getLogger().addHandler(ArgusHandler())
logger = logging.getLogger("serverless")


def handler(event, context):
    """Example serverless handler with Argus instrumentation."""
    # Start tracking this invocation
    argus.start_invocation(
        function_name="handler",
        invocation_id=getattr(context, "aws_request_id", ""),
    )

    try:
        result = process_request(event)

        argus.end_invocation(status="ok")
        argus.flush_sync()

        return {"statusCode": 200, "body": result}

    except Exception as e:
        argus.capture_exception(e)
        argus.end_invocation(status="error", error=str(e))
        argus.flush_sync()

        return {"statusCode": 500, "body": str(e)}


@trace("process_request")
def process_request(event):
    """Example business logic with breadcrumbs and logging."""
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")

    argus.add_breadcrumb("request", "Parsing event", {"path": path, "method": method})
    logger.info("Processing request: %s %s", method, path)

    # Send custom events for tracking
    argus.event("request_processed", {
        "path": path,
        "method": method,
    })

    argus.add_breadcrumb("request", "Business logic complete")
    logger.info("Request processed successfully")

    return '{"message": "Hello from Argus!"}'


def error_handler(event, context):
    """Second handler demonstrating error capture with breadcrumbs."""
    argus.start_invocation(
        function_name="error_handler",
        invocation_id=getattr(context, "aws_request_id", ""),
    )

    argus.add_breadcrumb("error_handler", "Invocation started", {
        "function": "error_handler",
        "path": event.get("path", "/"),
    })

    try:
        argus.add_breadcrumb("error_handler", "Validating input")
        # Simulate a validation failure
        raise ValueError("Missing required field: user_id")

    except Exception as e:
        logger.error("Error handler failed: %s", e)
        argus.add_breadcrumb("error_handler", "Exception caught", {"error": str(e)})
        argus.capture_exception(e)
        argus.end_invocation(status="error", error=str(e))
        argus.flush_sync()

        return {"statusCode": 500, "body": str(e)}
